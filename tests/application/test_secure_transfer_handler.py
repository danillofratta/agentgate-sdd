from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.execution_conflict import ExecutionConflict
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.domain.entities.account import Account
from agentgate.domain.entities.approval import Approval
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from tests.application.test_execute_operation_handler import (
    FakeExecutionWork,
    balance_operation,
    execution_handler,
)
from tests.domain.test_request_values import transfer


def transfer_operation(principal, clock, amount=10000):
    required = amount > 10000
    return replace(
        balance_operation(principal, clock),
        request=transfer(amount),
        policy=PolicyDecision(
            Decision.REQUIRE_APPROVAL if required else Decision.ALLOW,
            Reason.APPROVAL_REQUIRED if required else Reason.PERMITTED,
            PolicyVersion("v1"),
        ),
    )


def grant(operation, principal, clock):
    human = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
    return Approval(operation).decide(human, ApprovalDecision.APPROVE, clock.now())


class TransferWork(FakeExecutionWork):
    def __init__(self, operation, principal, approval=None):
        super().__init__(operation)
        self.current_principal = principal
        self.approval = approval
        self.ledger = {
            AccountId("acct-alice"): Account(AccountId("acct-alice"), 1000000),
            AccountId("acct-bob"): Account(AccountId("acct-bob"), 1000000),
        }
        self.accounts = SimpleNamespace(
            facts=lambda: tuple(account.facts() for account in self.ledger.values()),
            save=lambda account: self.ledger.update({account.id: account}),
        )
        self.approvals = SimpleNamespace(
            get=lambda operation_id: self.approval,
            save_consumption=lambda approval: setattr(self, "approval", approval),
        )
        self.active = False

    def __enter__(self):
        super().__enter__()
        self.saved = deepcopy((self.ledger, self.approval))
        self.active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        super().__exit__(exc_type, exc, tb)
        if exc_type:
            self.ledger, self.approval = self.saved
        self.active = False


class TransferTools:
    def __init__(self):
        self.calls = []

    def dispatch(self, tool, arguments, accounts):
        self.calls.append((tool, arguments, accounts))
        return arguments


@pytest.mark.parametrize("amount", [1, 10000, 10001, 100000])
def test_allow_and_human_approved_fake_port_transfer(principal, clock, amount):
    operation = transfer_operation(principal, clock, amount)
    approval = grant(operation, principal, clock) if amount > 10000 else None
    if approval:
        operation = approval.operation
    work, tools = TransferWork(operation, principal, approval), TransferTools()
    result = execution_handler(work, tools, clock).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED
    assert result.result == operation.request.arguments
    assert result.operation.policy == operation.policy
    assert result.operation.execution_authorization.decision == Decision.ALLOW
    assert result.operation.execution_authorization.reason == (
        Reason.HUMAN_APPROVED if approval else Reason.PERMITTED
    )
    assert [account.balance_cents for account in work.ledger.values()] == [
        1000000 - amount,
        1000000 + amount,
    ]
    assert sum(account.balance_cents for account in work.ledger.values()) == 2000000
    assert work.approval is None or work.approval.state == ApprovalState.CONSUMED
    before = deepcopy((work.ledger, work.approval, work.events))
    clock.value += timedelta(seconds=1000)
    assert (
        execution_handler(work, tools, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
        == result
    )
    assert (work.ledger, work.approval, work.events) == before
    assert len(tools.calls) == 1 and work.commits == 2


@pytest.mark.parametrize(
    "failure",
    [
        "pending",
        "role",
        "owner",
        "tool",
        "source",
        "revoked",
        "funds",
        "destination",
        "expired",
        "stale",
        "changed_arguments",
        "changed_owner",
        "rejected",
        "overflow",
    ],
)
def test_execution_revalidation_denies_without_consuming_approval(principal, clock, failure):
    pending = transfer_operation(principal, clock, 10001)
    approval = grant(pending, principal, clock)
    operation = approval.operation
    if failure == "pending":
        operation, approval = pending, Approval(pending)
    elif failure == "rejected":
        human = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
        approval = Approval(pending).decide(human, ApprovalDecision.REJECT, clock.now())
        operation = approval.operation
    work, tools = TransferWork(operation, principal, approval), TransferTools()
    caller = principal
    if failure == "role":
        caller = replace(principal, role=Role.APPROVER)
    elif failure == "owner":
        caller = replace(principal, id=PrincipalId("principal-other"))
    elif failure == "tool":
        work.current_principal = replace(principal, tools=frozenset())
    elif failure == "source":
        work.current_principal = replace(principal, source_accounts=frozenset())
    elif failure == "revoked":
        work.current_principal = replace(principal, role=Role.APPROVER)
    elif failure == "funds":
        work.ledger[AccountId("acct-alice")] = Account(AccountId("acct-alice"), 10000)
    elif failure == "destination":
        del work.ledger[AccountId("acct-bob")]
    elif failure == "expired":
        clock.value += timedelta(seconds=300)
    elif failure == "stale":
        object.__setattr__(
            operation, "policy", replace(operation.policy, version=PolicyVersion("v2"))
        )
    elif failure == "changed_arguments":
        work.operation = replace(operation, request=transfer(10002)).transition(
            OperationState.READY
        )
    elif failure == "changed_owner":
        work.approval = replace(
            approval, operation=replace(pending, principal_id=PrincipalId("principal-other"))
        )
    elif failure == "overflow":
        work.ledger[AccountId("acct-bob")] = Account(AccountId("acct-bob"), 2**63 - 1)
    before = deepcopy((work.operation, work.ledger, work.approval))
    with pytest.raises(
        (ExecutionConflict, Forbidden, NotFound, InvariantViolation, ExecutionUnavailable)
    ):
        execution_handler(work, tools, clock).handle(ExecuteOperationCommand(caller, operation.id))
    if failure == "overflow":
        assert work.operation == before[0].transition(OperationState.FAILED)
        assert (work.ledger, work.approval) == before[1:]
        assert work.commits == 2 and len(work.events) == 2
    else:
        assert (work.operation, work.ledger, work.approval) == before
        assert not work.events and not work.commits
    assert len(tools.calls) == int(failure == "overflow")


def test_fresh_principal_and_policy_are_loaded_inside_transaction(principal, clock):
    operation = transfer_operation(principal, clock)
    work, tools = TransferWork(operation, principal), TransferTools()
    observed = []

    def evaluate(snapshot):
        assert work.active
        observed.append(snapshot)
        assert snapshot.accounts == work.accounts.facts()
        return operation.policy

    handler = execution_handler(work, tools, clock, SimpleNamespace(evaluate=evaluate))

    def current(principal_id):
        assert work.active and principal_id == principal.id
        return work.current_principal

    handler._principals = SimpleNamespace(get_principal=current)
    handler.handle(ExecuteOperationCommand(principal, operation.id))
    assert len(observed) == 2 and len(tools.calls) == 1
