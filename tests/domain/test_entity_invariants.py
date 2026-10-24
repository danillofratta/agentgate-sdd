from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from agentgate.domain.entities.account import Account
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.approval_deadline import ApprovalDeadline
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint
from agentgate.domain.value_objects.role import Role
from tests.domain.test_request_values import transfer


@pytest.fixture
def operation(principal, clock):
    return Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("request"),
        transfer(),
        PolicyDecision(Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")),
        clock.now(),
    )


@pytest.fixture
def approver():
    return Principal(PrincipalId("principal-human"), Role.APPROVER, frozenset(), frozenset())


def test_account_transfer_conserves_funds_and_is_immutable():
    source = Account(AccountId("acct-alice"), 100)
    destination = Account(AccountId("acct-bob"), 0)
    debited, credited = source.transfer_to(destination, Money(100))
    assert (debited.balance_cents, credited.balance_cents) == (0, 100)
    assert debited.balance_cents + credited.balance_cents == source.balance_cents
    assert debited.id == source.id and credited.id == destination.id
    assert (source.balance_cents, destination.balance_cents) == (100, 0)
    with pytest.raises(FrozenInstanceError):
        source.id = destination.id


@pytest.mark.parametrize("case", ["same", "funds", "overflow", "untyped_amount", "untyped_account"])
def test_account_invalid_transfer_leaves_both_originals_unchanged(case):
    source = Account(AccountId("acct-alice"), 10)
    destination = Account(AccountId("acct-bob"), 2**63 - 1 if case == "overflow" else 0)
    before = (source.facts(), destination.facts())
    with pytest.raises(InvariantViolation):
        source.transfer_to(
            source if case == "same" else "acct-bob" if case == "untyped_account" else destination,
            1 if case == "untyped_amount" else Money(11 if case == "funds" else 1),
        )
    assert (source.facts(), destination.facts()) == before


@pytest.mark.parametrize("value", [None, True, -1, 1.5, "100", 2**63])
def test_account_construction_cannot_bypass_balance_validation(value):
    with pytest.raises(InvariantViolation):
        Account(AccountId("acct-alice"), value)


@pytest.mark.parametrize(
    "factory,valid,invalid",
    [
        (AccountId, "acct-a", [None, True, "acct-A", "acct-" + "a" * 33, "acct-a\n"]),
        (PrincipalId, "principal-a", [1, "principal-", "../principal-a", "principal-a\n"]),
        (
            OperationId,
            "abcdefab-0000-4000-8000-000000000001",
            [None, "ABCDEFAB-0000-4000-8000-000000000001", "not-a-uuid"],
        ),
        (PolicyVersion, "v1", [1, "v0", "v01", "v1\n", "v1000000000"]),
        (IdempotencyKey, "A_9-z", [True, "", "a" * 65, "á", "key\n"]),
        (RequestFingerprint, "a" * 64, [None, 1, "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n"]),
    ],
)
def test_immutable_values_validate_without_http(factory, valid, invalid):
    value = factory(valid)
    assert hash(value) == hash(factory(valid))
    with pytest.raises(FrozenInstanceError):
        value.value = "changed"
    for raw in invalid:
        with pytest.raises(InvariantViolation):
            factory(raw)


@pytest.mark.parametrize(
    "decision,reason,version",
    [
        ("ALLOW", Reason.PERMITTED, PolicyVersion("v1")),
        (Decision.ALLOW, "PERMITTED", PolicyVersion("v1")),
        (Decision.ALLOW, Reason.PERMITTED, "v1"),
        (Decision.ALLOW, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")),
        (Decision.DENY, Reason.PERMITTED, PolicyVersion("v1")),
        (Decision.DENY, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")),
        (Decision.REQUIRE_APPROVAL, Reason.PERMITTED, PolicyVersion("v1")),
    ],
)
def test_policy_decision_rejects_coercion_and_inconsistent_reasons(decision, reason, version):
    with pytest.raises(InvariantViolation):
        PolicyDecision(decision, reason, version)


def test_deadline_is_immutable_utc_and_exactly_300_seconds(clock):
    deadline = ApprovalDeadline(clock.now())
    assert deadline.expires_at - deadline.created_at == timedelta(seconds=300)
    assert not deadline.expired(deadline.expires_at - timedelta(microseconds=1))
    assert deadline.expired(deadline.expires_at)
    assert deadline.expired(deadline.expires_at + timedelta(microseconds=1))
    with pytest.raises(InvariantViolation):
        deadline.expired(clock.now() - timedelta(microseconds=1))
    with pytest.raises(FrozenInstanceError):
        deadline.created_at = deadline.expires_at


@pytest.mark.parametrize(
    "value",
    [
        None,
        "2026-01-01",
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        datetime.max.replace(tzinfo=UTC),
    ],
)
def test_invalid_deadlines(value):
    with pytest.raises(InvariantViolation):
        ApprovalDeadline(value)


def test_operation_initial_states_and_transition_graph(operation):
    initial = {
        Decision.ALLOW: (Reason.PERMITTED, OperationState.READY),
        Decision.DENY: (Reason.LIMIT_EXCEEDED, OperationState.DENIED),
        Decision.REQUIRE_APPROVAL: (Reason.APPROVAL_REQUIRED, OperationState.PENDING_APPROVAL),
    }
    edges = {
        OperationState.PENDING_APPROVAL: {
            OperationState.READY,
            OperationState.REJECTED,
            OperationState.EXPIRED,
        },
        OperationState.READY: {
            OperationState.SUCCEEDED,
            OperationState.DENIED,
            OperationState.EXPIRED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        },
    }
    states = {}
    for decision, (reason, state) in initial.items():
        item = replace(operation, policy=PolicyDecision(decision, reason, PolicyVersion("v1")))
        assert item.state == state
        states[state] = item
    states.update(
        {
            state: states[OperationState.READY].transition(state)
            for state in edges[OperationState.READY]
        }
    )
    states[OperationState.REJECTED] = operation.transition(OperationState.REJECTED)
    for source, item in states.items():
        for target in OperationState:
            if target in edges.get(source, set()):
                updated = item.transition(target)
                assert updated.state == target and item.state == source
                for field in ("id", "principal_id", "key", "request", "policy", "created_at"):
                    assert getattr(updated, field) == getattr(item, field)
            else:
                with pytest.raises(InvariantViolation):
                    item.transition(target)
    with pytest.raises(InvariantViolation):
        operation.transition("READY")


@pytest.mark.parametrize("field", ["id", "principal_id", "key", "request", "policy", "created_at"])
def test_operation_rejects_untyped_constructor_inputs_and_identity_changes(operation, field):
    with pytest.raises(InvariantViolation):
        replace(operation, **{field: "untrusted"})
    with pytest.raises(FrozenInstanceError):
        setattr(operation, field, "untrusted")


def test_approval_grant_and_consume_are_explicit_immutable_transitions(operation, approver, clock):
    pending = Approval(operation)
    granted = pending.decide(approver, ApprovalDecision.APPROVE, clock.now())
    assert pending.state == ApprovalState.PENDING and pending.decision is None
    assert granted.state == ApprovalState.GRANTED
    assert granted.operation.state == OperationState.READY
    assert granted.operation.policy == operation.policy
    assert granted.approver_id == approver.id and granted.decided_at == clock.now()
    consumed = granted.consume(granted.operation, PolicyVersion("v1"), clock.now())
    assert consumed.state == ApprovalState.CONSUMED and consumed.consumed_at == clock.now()
    assert granted.state == ApprovalState.GRANTED
    with pytest.raises(FrozenInstanceError):
        consumed.operation = replace(operation, request=transfer(1))


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_approval_cannot_be_decided_twice(operation, approver, clock, decision):
    decided = Approval(operation).decide(approver, decision, clock.now())
    for next_decision in ApprovalDecision:
        with pytest.raises(InvariantViolation):
            decided.decide(approver, next_decision, clock.now())
    if decision == ApprovalDecision.REJECT:
        assert decided.operation.state == OperationState.REJECTED
        with pytest.raises(InvariantViolation):
            decided.consume(decided.operation, PolicyVersion("v1"), clock.now())


def test_approval_requires_separate_trusted_approver(operation, principal, approver, clock):
    pending = Approval(operation)
    for untrusted in (principal, replace(approver, id=principal.id), "APPROVER"):
        with pytest.raises(InvariantViolation):
            pending.decide(untrusted, ApprovalDecision.APPROVE, clock.now())
    with pytest.raises(InvariantViolation):
        pending.decide(approver, "APPROVE", clock.now())
    with pytest.raises(InvariantViolation):
        pending.consume(operation, PolicyVersion("v1"), clock.now())


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_approval_exact_expiry_for_pending_and_granted(operation, approver, offset):
    pending = Approval(operation)
    granted = pending.decide(approver, ApprovalDecision.APPROVE, operation.created_at)
    now = pending.expires_at + timedelta(microseconds=offset)
    if offset < 0:
        assert (
            pending.decide(approver, ApprovalDecision.APPROVE, now).state == ApprovalState.GRANTED
        )
        assert (
            granted.consume(granted.operation, PolicyVersion("v1"), now).state
            == ApprovalState.CONSUMED
        )
        with pytest.raises(InvariantViolation):
            pending.expire(now)
    else:
        with pytest.raises(InvariantViolation):
            pending.decide(approver, ApprovalDecision.APPROVE, now)
        with pytest.raises(InvariantViolation):
            granted.consume(granted.operation, PolicyVersion("v1"), now)
        for approval in (pending, granted):
            expired = approval.expire(now)
            assert expired.state == ApprovalState.EXPIRED
            assert expired.operation.state == OperationState.EXPIRED
            with pytest.raises(InvariantViolation):
                expired.decide(approver, ApprovalDecision.APPROVE, now)
            with pytest.raises(InvariantViolation):
                expired.expire(now)


def test_approval_cannot_be_reused_for_changed_binding(operation, approver, clock):
    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, clock.now())
    bound = granted.operation
    changes = {
        "id": OperationId("00000000-0000-4000-8000-000000000002"),
        "principal_id": PrincipalId("principal-other"),
        "key": IdempotencyKey("other"),
        "request": transfer(10002),
        "policy": replace(bound.policy, version=PolicyVersion("v2")),
        "created_at": bound.created_at + timedelta(seconds=1),
    }
    for field, value in changes.items():
        changed = replace(bound, **{field: value}).transition(OperationState.READY)
        with pytest.raises(InvariantViolation):
            granted.consume(changed, PolicyVersion("v1"), clock.now())
    with pytest.raises(InvariantViolation):
        granted.consume(bound, PolicyVersion("v2"), clock.now())
    with pytest.raises(InvariantViolation):
        granted.consume(bound, "v1", clock.now())
    consumed = granted.consume(bound, PolicyVersion("v1"), clock.now())
    with pytest.raises(InvariantViolation):
        consumed.consume(bound, PolicyVersion("v1"), clock.now())
    with pytest.raises(InvariantViolation):
        consumed.expire(consumed.expires_at)


def test_approval_rejects_non_utc_or_backwards_transition_time(operation, approver, clock):
    pending = Approval(operation)
    for now in (datetime(2026, 1, 1), "now", clock.now() - timedelta(seconds=1)):
        with pytest.raises(InvariantViolation):
            pending.decide(approver, ApprovalDecision.APPROVE, now)
    granted = pending.decide(approver, ApprovalDecision.APPROVE, clock.now() + timedelta(seconds=5))
    with pytest.raises(InvariantViolation):
        granted.consume(granted.operation, PolicyVersion("v1"), clock.now())


def test_fingerprint_represents_exact_typed_request():
    first = transfer(1)
    equivalent = transfer(1)
    assert isinstance(first.fingerprint, RequestFingerprint)
    assert first.fingerprint == equivalent.fingerprint
    assert first.fingerprint != transfer(2).fingerprint
