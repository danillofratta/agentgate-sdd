import builtins
import os
import time
import uuid
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from agentgate.domain.entities.account import Account
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.enums.approval_decision import ApprovalDecision
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.role import Role
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.approver_required import ApproverRequired
from agentgate.domain.exceptions.insufficient_funds import InsufficientFunds
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from tests.domain.test_request_values import transfer


@pytest.fixture
def operation(principal, clock):
    return Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("facts"),
        transfer(),
        PolicyDecision(Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")),
        clock.now(),
    )


@pytest.fixture
def approver():
    return Principal(PrincipalId("principal-human"), Role.APPROVER, frozenset(), frozenset())


@pytest.fixture
def facts(operation, approver, clock):
    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, clock.now())
    succeeded = granted.operation.transition(OperationState.SUCCEEDED)
    return (
        operation.requested_event(),
        granted.decided_event(),
        succeeded.executed_event(clock.now()),
    )


@pytest.mark.parametrize(
    "decision,reason",
    [
        (Decision.ALLOW, Reason.PERMITTED),
        (Decision.DENY, Reason.LIMIT_EXCEEDED),
        (Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED),
    ],
)
def test_request_fact_preserves_original_policy_and_time(operation, decision, reason):
    item = replace(operation, policy=PolicyDecision(decision, reason, PolicyVersion("v1")))
    event = item.requested_event()
    assert event == OperationRequestedEvent(
        item.id, item.principal_id, item.request.tool, item.policy, item.created_at
    )
    assert item.requested_event() == event
    if decision == Decision.ALLOW:
        assert item.transition(OperationState.SUCCEEDED).requested_event() == event


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_decision_fact_binds_exact_operation_and_retains_decision(
    operation, approver, decision, principal
):
    pending = Approval(operation)
    now = operation.created_at + timedelta(seconds=1)
    decided = pending.decide(approver, decision, now)
    event = decided.decided_event()
    assert event == ApprovalDecidedEvent(
        operation.id,
        operation.principal_id,
        approver.id,
        operation.request.fingerprint,
        operation.policy.version,
        decision,
        now,
        operation.request.tool,
    )
    assert decided.decided_event() == event
    with pytest.raises(InvalidTransition, match="^INVALID_APPROVAL_TRANSITION$"):
        pending.decided_event()
    with pytest.raises(InvalidTransition):
        pending.expire(pending.expires_at).decided_event()
    if decision == ApprovalDecision.APPROVE:
        assert (
            decided.consume(
                decided.operation, operation.policy.version, now, principal=principal
            ).decided_event()
            == event
        )
        assert decided.expire(decided.expires_at).decided_event() == event


def test_execution_fact_requires_success_and_explicit_valid_time(operation, approver):
    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, operation.created_at)
    ready = granted.operation
    succeeded = ready.transition(OperationState.SUCCEEDED)
    now = operation.created_at + timedelta(seconds=2)
    event = succeeded.executed_event(now)
    assert event == OperationExecutedEvent(
        operation.id,
        operation.principal_id,
        operation.request.tool,
        operation.request.fingerprint,
        operation.policy.version,
        now,
    )
    assert succeeded.executed_event(now) == event
    assert ready.state == OperationState.READY
    for item in (
        operation,
        ready,
        *(
            ready.transition(state)
            for state in (
                OperationState.DENIED,
                OperationState.EXPIRED,
                OperationState.FAILED,
                OperationState.TIMED_OUT,
            )
        ),
    ):
        with pytest.raises(InvalidTransition, match="^INVALID_OPERATION_TRANSITION$"):
            item.executed_event(now)
    with pytest.raises(InvalidTransition):
        succeeded.executed_event(operation.created_at - timedelta(microseconds=1))
    for invalid_time in (None, "now", datetime(2026, 1, 1)):
        with pytest.raises(InvariantViolation, match="^UTC_REQUIRED$"):
            succeeded.executed_event(invalid_time)


def test_entity_fact_generation_needs_no_io_environment_clock_or_random_ids(
    operation, approver, monkeypatch
):
    now = operation.created_at

    def forbidden(*args, **kwargs):
        raise AssertionError("Domain fact generation must be deterministic and pure")

    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, "open", forbidden)
        isolated.setattr(os, "getenv", forbidden)
        isolated.setattr(time, "time", forbidden)
        isolated.setattr(time, "monotonic", forbidden)
        isolated.setattr(uuid, "uuid4", forbidden)
        pending = Approval(operation)
        granted = pending.decide(approver, ApprovalDecision.APPROVE, now)
        succeeded = granted.operation.transition(OperationState.SUCCEEDED)
        request = operation.requested_event()
        decision = granted.decided_event()
        execution = succeeded.executed_event(now)
        assert operation.requested_event() == request
        assert granted.decided_event() == decision
        assert succeeded.executed_event(now) == execution


def test_all_event_fields_are_validated_immutable_and_hashable(facts):
    for event in facts:
        assert hash(event) == hash(replace(event))
        for field in fields(event):
            with pytest.raises(FrozenInstanceError):
                setattr(event, field.name, "changed")
            for untyped in (None, True, "rejected\nsecret", [], {}):
                with pytest.raises(InvariantViolation) as error:
                    replace(event, **{field.name: untyped})
                assert "secret" not in str(error.value)
        for invalid_time in (
            datetime(2026, 1, 1),
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        ):
            with pytest.raises(InvariantViolation, match="^UTC_REQUIRED$"):
                replace(event, occurred_at=invalid_time)
    with pytest.raises(InvariantViolation, match="^INVALID_APPROVAL_EVENT$"):
        replace(facts[1], approver_id=facts[1].principal_id)


def test_typed_failures_preserve_base_contract_codes_and_original_state(
    operation, approver, principal
):
    pending = Approval(operation)
    granted = pending.decide(approver, ApprovalDecision.APPROVE, operation.created_at)
    source = Account(AccountId("acct-alice"), 0)
    destination = Account(AccountId("acct-bob"), 0)
    cases = (
        (
            InvalidTransition,
            "INVALID_OPERATION_TRANSITION",
            lambda: operation.transition(OperationState.SUCCEEDED),
        ),
        (
            InvalidTransition,
            "INVALID_APPROVAL_TRANSITION",
            lambda: granted.decide(approver, ApprovalDecision.REJECT, operation.created_at),
        ),
        (
            ApproverRequired,
            "APPROVER_REQUIRED",
            lambda: pending.decide(principal, ApprovalDecision.APPROVE, operation.created_at),
        ),
        (
            ApprovalBindingMismatch,
            "APPROVAL_BINDING_MISMATCH",
            lambda: granted.consume(
                granted.operation, PolicyVersion("v2"), operation.created_at, principal=principal
            ),
        ),
        (
            InsufficientFunds,
            "INSUFFICIENT_FUNDS",
            lambda: source.transfer_to(destination, Money(1)),
        ),
    )
    before = (operation, pending, granted, source, destination)
    for exception_type, code, action in cases:
        with pytest.raises(exception_type, match=f"^{code}$") as error:
            action()
        assert isinstance(error.value, InvariantViolation)
        assert isinstance(error.value, ValueError)
    assert (operation, pending, granted, source, destination) == before
