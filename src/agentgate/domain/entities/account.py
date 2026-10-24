from dataclasses import dataclass

from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId


@dataclass(frozen=True)
class Account:
    id: AccountId
    balance_cents: int

    def __post_init__(self) -> None:
        AccountFacts(self.id, self.balance_cents)

    def facts(self) -> AccountFacts:
        return AccountFacts(self.id, self.balance_cents)
