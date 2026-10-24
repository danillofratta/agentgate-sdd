from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId


@dataclass(frozen=True)
class AccountFacts:
    id: AccountId
    balance_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, AccountId) or type(self.balance_cents) is not int:
            raise InvariantViolation("INVALID_ACCOUNT")
        if not 0 <= self.balance_cents <= 2**63 - 1:
            raise InvariantViolation("INVALID_BALANCE")
