from copy import deepcopy
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.domain.entities.operation import Operation
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from tests.domain.test_request_values import transfer


def balance_operation(principal, clock):
    return Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("execute"),
        OperationRequest(BalanceArguments(AccountId("acct-alice"))),
        PolicyDecision(Decision.ALLOW, Reason.PERMITTED, PolicyVersion("v1")),
        clock.now(),
    )


class FakeExecutionWork:
    def __init__(self, operation):
        self.operation = operation
        self.result = None
        self.events = []
        self.commits = 0
        self.current_principal = None
        self.operations = SimpleNamespace(
            get=lambda operation_id: self.operation,
            save_execution=self.save_execution,
            get_result=lambda operation_id: self.result,
        )
        self.accounts = SimpleNamespace(
            facts=lambda: (AccountFacts(AccountId("acct-alice"), 12345),)
        )
        self.audit = SimpleNamespace(append=self.events.append)

    def save_execution(self, operation, result):
        self.operation, self.result = operation, result

    def __enter__(self):
        self.before = deepcopy((self.operation, self.result, self.events))
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.operation, self.result, self.events = self.before

    def commit(self):
        self.commits += 1


class FakeTools:
    def __init__(self):
        self.calls = []
        self.result = BalanceResult(AccountId("acct-alice"), 12345)

    def dispatch(self, tool, arguments, accounts):
        self.calls.append((tool, arguments, accounts))
        return self.result


def execution_handler(work, tools, clock, policy=None, principal=None):
    from tests.conftest import principal as principal_fixture

    if work.current_principal is None:
        work.current_principal = principal or principal_fixture.__wrapped__()

    def no_sleep(seconds):
        pytest.fail("5.1 must not retry or sleep")

    return ExecuteOperationHandler(
        lambda: work,
        tools,
        policy or EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=no_sleep),
        SimpleNamespace(get_principal=lambda principal_id: work.current_principal),
    )


def test_balance_execution_fake_ports_and_exact_schema(principal, clock):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()
    result = execution_handler(work, tools, clock).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED
    assert type(result.result) is BalanceResult
    assert [field.name for field in fields(result.result)] == [
        "account_id",
        "balance_cents",
        "currency",
    ]
    assert result.result == BalanceResult(AccountId("acct-alice"), 12345, "USD")
    assert len(tools.calls) == work.commits == 1
    assert tools.calls[0][1] is operation.request.arguments
    assert isinstance(work.events[0], OperationDispatchedEvent)
    assert isinstance(work.events[1], OperationExecutedEvent)
    assert work.accounts.facts() == (AccountFacts(AccountId("acct-alice"), 12345),)


@pytest.mark.parametrize(
    "change, error",
    [
        ({"role": Role.APPROVER}, Forbidden),
        ({"id": PrincipalId("principal-other")}, NotFound),
        ({"tools": frozenset()}, Forbidden),
        ({"source_accounts": frozenset()}, Forbidden),
    ],
)
def test_direct_handler_authorization(principal, clock, change, error):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()
    work.current_principal = replace(principal, **change)
    with pytest.raises(error):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(replace(principal, **change), operation.id)
        )
    assert not tools.calls and not work.events and not work.commits


@pytest.mark.parametrize(
    "state", [state for state in OperationState if state != OperationState.READY]
)
def test_only_ready_operation_can_dispatch(principal, clock, state):
    operation = balance_operation(principal, clock)
    object.__setattr__(operation, "_state", state)
    work, tools = FakeExecutionWork(operation), FakeTools()
    with pytest.raises((InvalidTransition, ExecutionUnavailable)):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert not tools.calls and not work.events and not work.commits


@pytest.mark.parametrize("invalid", ["missing", "wrong_id", "stale", "denied", "unknown_tool"])
def test_invalid_stored_operations_fail_closed(principal, clock, invalid):
    operation = balance_operation(principal, clock)
    stored = operation
    if invalid == "missing":
        stored = None
    elif invalid == "wrong_id":
        stored = replace(operation, id=OperationId("00000000-0000-4000-8000-000000000002"))
    elif invalid == "stale":
        stored = replace(operation, policy=replace(operation.policy, version=PolicyVersion("v2")))
    elif invalid == "denied":
        stored = replace(
            operation,
            policy=PolicyDecision(Decision.DENY, Reason.POLICY_UNCERTAIN, PolicyVersion("v1")),
        )
    else:
        # A compromised/fake repository must not enable arbitrary tool dispatch.
        stored = SimpleNamespace(
            id=operation.id, principal_id=principal.id, request=SimpleNamespace(tool="unknown-tool")
        )
    work, tools = FakeExecutionWork(stored), FakeTools()
    with pytest.raises((NotFound, Forbidden, InvalidTransition)):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert not tools.calls and not work.events and not work.commits


@pytest.mark.parametrize(
    "facts",
    [
        None,
        (),
        ("untrusted",),
        (AccountFacts(AccountId("acct-alice"), 1), AccountFacts(AccountId("acct-alice"), 2)),
    ],
)
def test_missing_or_invalid_account_context(principal, clock, facts):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()
    work.accounts.facts = lambda: facts
    with pytest.raises(Forbidden):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert not tools.calls and not work.events


@pytest.mark.parametrize("failure", ["raise", "none", "stale", "deny"])
def test_policy_uncertainty_prevents_dispatch(principal, clock, failure):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()

    def evaluate(snapshot):
        if failure == "raise":
            raise RuntimeError("SECRET_SENTINEL\nforged-log")
        if failure == "none":
            return None
        if failure == "stale":
            return replace(operation.policy, version=PolicyVersion("v2"))
        return PolicyDecision(Decision.DENY, Reason.POLICY_UNCERTAIN, PolicyVersion("v1"))

    with pytest.raises(Forbidden) as error:
        execution_handler(work, tools, clock, SimpleNamespace(evaluate=evaluate)).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert not tools.calls and not work.events and not work.commits
    assert "SECRET_SENTINEL" not in str(error.value)


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"account_id": "acct-alice", "balance_cents": 1},
        BalanceResult(AccountId("acct-bob"), 1),
    ],
)
def test_invalid_tool_result_rolls_back(principal, clock, result):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()
    tools.result = result
    with pytest.raises(ExecutionUnavailable):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert len(tools.calls) == 1 and not work.events and not work.commits
    assert work.operation == operation and work.result is None


def test_transfer_missing_destination_never_dispatched(principal, clock):
    operation = replace(balance_operation(principal, clock), request=transfer(1))
    work, tools = FakeExecutionWork(operation), FakeTools()
    with pytest.raises(Forbidden):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert not tools.calls and not work.events and not work.commits


@pytest.mark.parametrize("extra", ["arguments", "role", "permissions", "policy_version"])
def test_command_accepts_no_client_overrides(principal, clock, extra):
    with pytest.raises(TypeError):
        ExecuteOperationCommand(
            principal, balance_operation(principal, clock).id, **{extra: "value"}
        )


@pytest.mark.parametrize("field", ["principal", "operation_id"])
def test_command_rejects_untyped_values(principal, clock, field):
    command = ExecuteOperationCommand(principal, balance_operation(principal, clock).id)
    with pytest.raises(InvariantViolation):
        replace(command, **{field: {"role": "APPROVER"}})


@pytest.mark.parametrize("success_audit", [False, True])
def test_fake_audit_failure_prevents_commit_and_pre_dispatch_failure_prevents_call(
    principal, clock, success_audit
):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()

    def append(event):
        if isinstance(event, OperationExecutedEvent) == success_audit:
            raise RuntimeError("audit unavailable")
        work.events.append(event)

    work.audit.append = append
    with pytest.raises(RuntimeError):
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert len(tools.calls) == int(success_audit)
    assert work.operation == operation and work.result is None
    assert not work.events and not work.commits


def test_tool_exception_is_sanitized_and_never_retried(principal, clock):
    operation = balance_operation(principal, clock)
    work, tools = FakeExecutionWork(operation), FakeTools()

    def broken_dispatch(*args):
        tools.calls.append(args)
        raise RuntimeError("SECRET_SENTINEL\nforged-log")

    tools.dispatch = broken_dispatch
    with pytest.raises(ExecutionUnavailable) as error:
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert len(tools.calls) == 1
    assert "SECRET_SENTINEL" not in str(error.value)
    assert not work.events and not work.commits and work.result is None
