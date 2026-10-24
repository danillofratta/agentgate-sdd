from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId


@dataclass(frozen=True)
class ExpireApprovalCommand:
    """Internal maintenance intent; never accepts caller-supplied time or binding."""

    operation_id: OperationId

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, OperationId):
            raise InvariantViolation("INVALID_COMMAND")
