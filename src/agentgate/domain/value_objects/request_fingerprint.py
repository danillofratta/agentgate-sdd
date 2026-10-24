import re
from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class RequestFingerprint:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not re.fullmatch("[0-9a-f]{64}", self.value):
            raise InvariantViolation("INVALID_FINGERPRINT")
