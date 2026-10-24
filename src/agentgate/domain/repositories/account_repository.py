from typing import Protocol

from agentgate.domain.entities.account import Account
from agentgate.domain.value_objects.account_facts import AccountFacts


class AccountRepository(Protocol):
    def save(self, account: Account) -> None: ...

    def facts(self) -> tuple[AccountFacts, ...]: ...
