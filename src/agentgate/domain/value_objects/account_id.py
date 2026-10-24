import re
from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class AccountId:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not re.fullmatch("acct-[a-z0-9]{1,32}", self.value):
            raise InvariantViolation("INVALID_ACCOUNT_ID")
