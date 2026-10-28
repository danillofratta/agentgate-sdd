import re
from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class PolicyVersion:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not re.fullmatch("v[1-9][0-9]{0,8}", self.value):
            raise InvariantViolation("INVALID_POLICY_VERSION")
