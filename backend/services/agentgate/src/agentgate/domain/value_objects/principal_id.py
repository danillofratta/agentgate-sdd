import re
from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class PrincipalId:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not re.fullmatch("principal-[a-z0-9-]{1,48}", self.value):
            raise InvariantViolation("INVALID_PRINCIPAL_ID")
