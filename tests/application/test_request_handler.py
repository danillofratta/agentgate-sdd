from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.features.evaluate_policy.handler import (
    EvaluatePolicyHandler,
)
from agentgate.features.evaluate_policy.query import EvaluatePolicyQuery
from agentgate.features.request_operation.command import (
    RequestOperationCommand,
)
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)
from tests.domain.test_request_values import transfer


class FakeUnitOfWork:
    def __init__(self):
        self.saved = {}
        self.events = []
        self.pending = []
        self.accounts = SimpleNamespace(
            facts=lambda: (
                AccountFacts(AccountId("acct-alice"), 1000000),
                AccountFacts(AccountId("acct-bob"), 1000000),
            )
        )
        self.operations = SimpleNamespace(find=self.find, add=self.add)
        self.approvals = SimpleNamespace(add=self.pending.append)
        self.audit = SimpleNamespace(append=self.events.append)
        self.commits = 0

    def find(self, principal_id, key):
        return self.saved.get((principal_id, key))

    def add(self, operation):
        self.saved[operation.principal_id, operation.key] = operation

    def __enter__(self):
        self.before = deepcopy((self.saved, self.pending, self.events))
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            saved, pending, events = self.before
            self.saved.clear()
            self.saved.update(saved)
            self.pending[:] = pending
            self.events[:] = events

    def commit(self):
        self.commits += 1


def handler(work, clock, policy=None):
    return RequestOperationHandler(
        lambda: work,
        policy or EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(next_id=lambda: "00000000-0000-4000-8000-000000000001"),
    )


def test_constructor_injected_handler_and_replay(principal, clock):
    work = FakeUnitOfWork()
    use_case = handler(work, clock)
    command = RequestOperationCommand(principal, IdempotencyKey("one"), transfer())
    first = use_case.handle(command)
    second = use_case.handle(command)
    assert first.created and (not second.created)
    assert first.operation == second.operation
    assert work.commits == len(work.events) == len(work.pending) == 1
    assert first.operation.policy.decision == Decision.REQUIRE_APPROVAL
    assert work.pending[0].operation == first.operation


def test_handler_conflict_and_principal_isolation(principal, clock):
    work = FakeUnitOfWork()
    use_case = handler(work, clock)
    command = RequestOperationCommand(principal, IdempotencyKey("one"), transfer())
    use_case.handle(command)
    with pytest.raises(IdempotencyConflict):
        use_case.handle(replace(command, request=transfer(1)))
    other = replace(principal, id=PrincipalId("principal-other"))
    assert use_case.handle(replace(command, principal=other)).created
    assert len(work.events) == 2


def test_direct_handler_checks_role_and_permissions(principal, clock):
    work = FakeUnitOfWork()
    use_case = handler(work, clock)
    with pytest.raises(Forbidden):
        use_case.handle(
            RequestOperationCommand(
                replace(principal, role=Role.APPROVER), IdempotencyKey("one"), transfer()
            )
        )
    assert not work.saved
    denied = use_case.handle(
        RequestOperationCommand(
            replace(principal, tools=frozenset()), IdempotencyKey("two"), transfer()
        )
    )
    assert denied.operation.policy.reason == Reason.TOOL_NOT_ALLOWED


@pytest.mark.parametrize("invalid_policy", [False, True])
def test_policy_uncertainty_fails_closed_and_is_audited(principal, clock, invalid_policy):

    def uncertain(snapshot):
        if invalid_policy:
            return None
        raise RuntimeError("SECRET_SENTINEL\nforged-log")

    work = FakeUnitOfWork()
    result = handler(work, clock, SimpleNamespace(evaluate=uncertain)).handle(
        RequestOperationCommand(principal, IdempotencyKey("one"), transfer())
    )
    assert result.operation.policy.decision == Decision.DENY
    assert result.operation.policy.reason == Reason.POLICY_UNCERTAIN
    assert len(work.events) == 1
    assert not work.pending
    assert "SECRET_SENTINEL" not in repr(work.events)


def test_missing_account_facts_fail_closed(principal, clock):
    work = FakeUnitOfWork()
    work.accounts.facts = lambda: None
    result = handler(work, clock).handle(
        RequestOperationCommand(principal, IdempotencyKey("one"), transfer())
    )
    assert result.operation.policy.reason == Reason.POLICY_UNCERTAIN


def test_audit_failure_rolls_back_request_and_approval(principal, clock):
    work = FakeUnitOfWork()

    def unavailable(event):
        raise RuntimeError("audit unavailable")

    work.audit.append = unavailable
    with pytest.raises(RuntimeError):
        handler(work, clock).handle(
            RequestOperationCommand(principal, IdempotencyKey("one"), transfer())
        )
    assert not work.saved and (not work.pending) and (not work.events) and (not work.commits)


def test_internal_query_is_pure(principal):
    use_case = EvaluatePolicyHandler()
    query = EvaluatePolicyQuery(PolicySnapshot(principal, transfer(), ()))
    assert use_case.handle(query) == use_case.handle(query)
    assert use_case.handle(query).decision == Decision.DENY
