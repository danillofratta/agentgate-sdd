from typing import Protocol

from agentgate.domain.value_objects.account_facts import AccountFacts


class AccountRepository(Protocol):
    def facts(self) -> tuple[AccountFacts, ...]: ...
