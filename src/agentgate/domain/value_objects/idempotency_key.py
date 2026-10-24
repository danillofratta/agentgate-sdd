import re
from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not re.fullmatch("[A-Za-z0-9_-]{1,64}", self.value):
            raise InvariantViolation("INVALID_IDEMPOTENCY_KEY")
