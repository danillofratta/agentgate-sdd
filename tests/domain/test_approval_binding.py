from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from agentgate.domain.entities.approval import Approval
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from tests.domain.test_entity_invariants import approver, operation

__all__ = ["approver", "operation"]


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_late_grant_keeps_creation_deadline(operation, approver, principal, clock, offset):
    pending = Approval(operation)
    clock.value = operation.created_at + timedelta(seconds=299)
    granted = pending.decide(approver, ApprovalDecision.APPROVE, clock.now())
    event = granted.decided_event()
    assert granted.expires_at == operation.created_at + timedelta(seconds=300)
    clock.value = granted.expires_at + timedelta(microseconds=offset)
    if offset < 0:
        consumed = granted.consume(
            granted.operation, operation.policy.version, clock.now(), principal=principal
        )
        assert consumed.state == ApprovalState.CONSUMED
        assert consumed.decided_event() == event
    else:
        with pytest.raises(InvalidTransition):
            granted.consume(
                granted.operation, operation.policy.version, clock.now(), principal=principal
            )
        expired = granted.expire(clock.now())
        assert expired.state == ApprovalState.EXPIRED
        assert expired.operation.state == OperationState.EXPIRED
        assert expired.operation.policy == operation.policy
        assert expired.decided_event() == event
    assert pending.state == ApprovalState.PENDING
    assert granted.state == ApprovalState.GRANTED


@pytest.mark.parametrize("caller", ["other_agent", "approver", "untyped"])
def test_exact_operation_is_not_a_bearer_approval(operation, approver, principal, clock, caller):
    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, clock.now())
    untrusted = {
        "other_agent": replace(principal, id=PrincipalId("principal-other")),
        "approver": replace(principal, role=Role.APPROVER),
        "untyped": {"id": principal.id, "role": Role.AGENT},
    }[caller]
    with pytest.raises(ApprovalBindingMismatch):
        granted.consume(
            granted.operation, operation.policy.version, clock.now(), principal=untrusted
        )
    assert granted.state == ApprovalState.GRANTED


@pytest.mark.parametrize("version", ["v2", "v999999999"])
def test_matching_unknown_policy_cannot_be_granted(operation, approver, clock, version):
    changed = replace(operation, policy=replace(operation.policy, version=PolicyVersion(version)))
    pending = Approval(changed)
    with pytest.raises(ApprovalBindingMismatch):
        pending.decide(approver, ApprovalDecision.APPROVE, clock.now())
    assert pending.state == ApprovalState.PENDING


def test_policy_change_invalidates_granted_approval(
    operation, approver, principal, clock, monkeypatch
):
    import agentgate.domain.entities.approval as approval_module

    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, clock.now())
    monkeypatch.setattr(approval_module, "CURRENT_POLICY_VERSION", PolicyVersion("v2"))
    for version in (PolicyVersion("v1"), PolicyVersion("v2")):
        with pytest.raises(ApprovalBindingMismatch):
            granted.consume(granted.operation, version, clock.now(), principal=principal)
    assert granted.state == ApprovalState.GRANTED
    assert granted.operation.policy == operation.policy


def test_matching_obsolete_policy_cannot_be_consumed(
    operation, approver, principal, clock, monkeypatch
):
    import agentgate.domain.entities.approval as approval_module

    # Model a persisted grant from a different policy deployment.
    version = PolicyVersion("v2")
    old = replace(operation, policy=replace(operation.policy, version=version))
    with monkeypatch.context() as previous_deployment:
        previous_deployment.setattr(approval_module, "CURRENT_POLICY_VERSION", version)
        granted = Approval(old).decide(approver, ApprovalDecision.APPROVE, clock.now())
    with pytest.raises(ApprovalBindingMismatch):
        granted.consume(granted.operation, version, clock.now(), principal=principal)
    assert granted.state == ApprovalState.GRANTED


@pytest.mark.parametrize("field", ["id", "principal_id", "request", "policy", "created_at"])
def test_bound_identity_cannot_be_assigned_after_grant(operation, approver, clock, field):
    granted = Approval(operation).decide(approver, ApprovalDecision.APPROVE, clock.now())
    with pytest.raises(FrozenInstanceError):
        setattr(granted.operation, field, None)
    with pytest.raises(FrozenInstanceError):
        granted.operation.request.arguments.amount.cents = 1
    with pytest.raises(FrozenInstanceError):
        granted.operation.request.fingerprint.value = "0" * 64
    with pytest.raises(FrozenInstanceError):
        granted.operation.policy.version.value = "v2"
