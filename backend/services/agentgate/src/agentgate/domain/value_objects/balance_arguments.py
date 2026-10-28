from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId


@dataclass(frozen=True)
class BalanceArguments:
    account_id: AccountId

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise InvariantViolation("INVALID_ACCOUNT_ID")
