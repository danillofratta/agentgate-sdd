from copy import copy
from dataclasses import dataclass, field
from datetime import datetime

from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.utc import require_utc


@dataclass(frozen=True)
class Operation:
    id: OperationId
    principal_id: PrincipalId
    key: IdempotencyKey
    request: OperationRequest
    policy: PolicyDecision
    created_at: datetime
    _state: OperationState = field(init=False)
    execution_authorization: PolicyDecision | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not all(
            (
                isinstance(self.id, OperationId),
                isinstance(self.principal_id, PrincipalId),
                isinstance(self.key, IdempotencyKey),
                isinstance(self.request, OperationRequest),
                isinstance(self.policy, PolicyDecision),
            )
        ):
            raise InvariantViolation("INVALID_OPERATION")
        require_utc(self.created_at)
        object.__setattr__(
            self,
            "_state",
            {
                Decision.ALLOW: OperationState.READY,
                Decision.DENY: OperationState.DENIED,
                Decision.REQUIRE_APPROVAL: OperationState.PENDING_APPROVAL,
            }[self.policy.decision],
        )

    @property
    def state(self) -> OperationState:
        return self._state

    def requested_event(self) -> OperationRequestedEvent:
        """Describe the original request without recording or delivering it."""
        return OperationRequestedEvent(
            self.id, self.principal_id, self.request.tool, self.policy, self.created_at
        )

    def executed_event(self, occurred_at: datetime) -> OperationExecutedEvent:
        """Describe successful completion using caller-supplied time, without dispatch."""
        require_utc(occurred_at)
        if self.state != OperationState.SUCCEEDED or occurred_at < self.created_at:
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")
        return OperationExecutedEvent(
            self.id,
            self.principal_id,
            self.request.tool,
            self.request.fingerprint,
            self.policy.version,
            occurred_at,
        )

    def transition(self, target: OperationState) -> "Operation":
        """Guard the lifecycle graph; request identity and original policy stay frozen."""
        allowed = {
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
        if not isinstance(target, OperationState) or target not in allowed.get(self.state, set()):
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")
        updated = copy(self)
        object.__setattr__(updated, "_state", target)
        return updated

    def authorize_execution(self, authorization: PolicyDecision) -> "Operation":
        expected = (
            Reason.HUMAN_APPROVED
            if self.policy.decision == Decision.REQUIRE_APPROVAL
            else Reason.PERMITTED
        )
        if (
            self.state != OperationState.READY
            or self.policy.decision == Decision.DENY
            or self.execution_authorization is not None
            or not isinstance(authorization, PolicyDecision)
            or authorization.decision != Decision.ALLOW
            or authorization.version != self.policy.version
            or authorization.reason != expected
        ):
            raise InvalidTransition("INVALID_EXECUTION_AUTHORIZATION")
        updated = copy(self)
        object.__setattr__(updated, "execution_authorization", authorization)
        return updated
