from dataclasses import dataclass

from agentgate.domain.exceptions.insufficient_funds import InsufficientFunds
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.money import Money


@dataclass(frozen=True)
class Account:
    id: AccountId
    balance_cents: int

    def __post_init__(self) -> None:
        AccountFacts(self.id, self.balance_cents)

    def facts(self) -> AccountFacts:
        return AccountFacts(self.id, self.balance_cents)

    def transfer_to(self, destination: "Account", amount: Money) -> tuple["Account", "Account"]:
        """Return both new balances together, leaving the originals unchanged on failure."""
        if not isinstance(destination, Account) or not isinstance(amount, Money):
            raise InvariantViolation("INVALID_TRANSFER")
        if self.id == destination.id:
            raise InvariantViolation("SAME_ACCOUNT_TRANSFER")
        if self.balance_cents < amount.cents:
            raise InsufficientFunds("INSUFFICIENT_FUNDS")
        return (
            Account(self.id, self.balance_cents - amount.cents),
            Account(destination.id, destination.balance_cents + amount.cents),
        )
