from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class ApproveOperationCommand:
    principal: Principal
    operation_id: OperationId
    decision: ApprovalDecision

    def __post_init__(self) -> None:
        if not (
            isinstance(self.principal, Principal)
            and isinstance(self.operation_id, OperationId)
            and isinstance(self.decision, ApprovalDecision)
        ):
            raise InvariantViolation("INVALID_COMMAND")
