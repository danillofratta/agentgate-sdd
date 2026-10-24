from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId


@dataclass(frozen=True)
class BalanceResult:
    account_id: AccountId
    balance_cents: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.account_id, AccountId)
            or type(self.balance_cents) is not int
            or not 0 <= self.balance_cents <= 2**63 - 1
            or self.currency != "USD"
        ):
            raise InvariantViolation("INVALID_BALANCE_RESULT")
