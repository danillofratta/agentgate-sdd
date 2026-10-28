from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class GetOperationQuery:
    principal: Principal
    operation_id: OperationId

    def __post_init__(self) -> None:
        if not isinstance(self.principal, Principal) or not isinstance(
            self.operation_id, OperationId
        ):
            raise InvariantViolation("INVALID_QUERY")
