from copy import copy
from dataclasses import dataclass, field
from datetime import datetime

from agentgate.domain.entities.operation import Operation
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.approval_deadline import ApprovalDeadline
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role


@dataclass(frozen=True)
class Approval:
    """Immutable lifecycle snapshots bound to one exact operation and policy."""

    operation: Operation
    state: ApprovalState = field(default=ApprovalState.PENDING, init=False)
    decision: ApprovalDecision | None = field(default=None, init=False)
    approver_id: PrincipalId | None = field(default=None, init=False)
    decided_at: datetime | None = field(default=None, init=False)
    consumed_at: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation, Operation)
            or self.operation.policy.decision != Decision.REQUIRE_APPROVAL
            or self.operation.state != OperationState.PENDING_APPROVAL
        ):
            raise InvariantViolation("APPROVAL_NOT_REQUIRED")
        ApprovalDeadline(self.operation.created_at)

    @property
    def deadline(self) -> ApprovalDeadline:
        return ApprovalDeadline(self.operation.created_at)

    @property
    def expires_at(self) -> datetime:
        return self.deadline.expires_at

    def decide(self, approver: Principal, decision: ApprovalDecision, now: datetime) -> "Approval":
        if (
            not isinstance(approver, Principal)
            or approver.role != Role.APPROVER
            or approver.id == self.operation.principal_id
        ):
            raise InvariantViolation("APPROVER_REQUIRED")
        if not isinstance(decision, ApprovalDecision):
            raise InvariantViolation("INVALID_APPROVAL_DECISION")
        if self.state != ApprovalState.PENDING or self.deadline.expired(now):
            raise InvariantViolation("INVALID_APPROVAL_TRANSITION")
        granted = decision == ApprovalDecision.APPROVE
        updated = copy(self)
        object.__setattr__(
            updated, "state", ApprovalState.GRANTED if granted else ApprovalState.REJECTED
        )
        object.__setattr__(updated, "decision", decision)
        object.__setattr__(updated, "approver_id", approver.id)
        object.__setattr__(updated, "decided_at", now)
        object.__setattr__(
            updated,
            "operation",
            self.operation.transition(OperationState.READY if granted else OperationState.REJECTED),
        )
        return updated

    def consume(self, operation: Operation, version: PolicyVersion, now: datetime) -> "Approval":
        if (
            self.state != ApprovalState.GRANTED
            or self.deadline.expired(now)
            or self.decided_at is None
            or now < self.decided_at
        ):
            raise InvariantViolation("INVALID_APPROVAL_TRANSITION")
        if (
            not isinstance(operation, Operation)
            or operation != self.operation
            or not isinstance(version, PolicyVersion)
            or version != self.operation.policy.version
        ):
            raise InvariantViolation("APPROVAL_BINDING_MISMATCH")
        updated = copy(self)
        object.__setattr__(updated, "state", ApprovalState.CONSUMED)
        object.__setattr__(updated, "consumed_at", now)
        return updated

    def expire(self, now: datetime) -> "Approval":
        if self.state not in {
            ApprovalState.PENDING,
            ApprovalState.GRANTED,
        } or not self.deadline.expired(now):
            raise InvariantViolation("INVALID_APPROVAL_TRANSITION")
        updated = copy(self)
        object.__setattr__(updated, "state", ApprovalState.EXPIRED)
        object.__setattr__(updated, "operation", self.operation.transition(OperationState.EXPIRED))
        return updated
