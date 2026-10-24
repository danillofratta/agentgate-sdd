from dataclasses import dataclass
from uuid import UUID

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class OperationId:
    value: str

    def __post_init__(self) -> None:
        try:
            if type(self.value) is not str or str(UUID(self.value)) != self.value:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise InvariantViolation("INVALID_OPERATION_ID") from None
