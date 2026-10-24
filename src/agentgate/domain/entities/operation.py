from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.utc import require_utc


@dataclass(frozen=True)
class Operation:
    id: OperationId
    principal_id: PrincipalId
    key: IdempotencyKey
    request: OperationRequest
    policy: PolicyDecision
    created_at: datetime

    def __post_init__(self) -> None:
        from agentgate.domain.exceptions.invariant_violation import InvariantViolation

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

    @property
    def state(self) -> OperationState:
        return {
            Decision.ALLOW: OperationState.READY,
            Decision.DENY: OperationState.DENIED,
            Decision.REQUIRE_APPROVAL: OperationState.PENDING_APPROVAL,
        }[self.policy.decision]
