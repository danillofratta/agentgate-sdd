import sqlite3

from agentgate.domain.entities.account import Account
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId


class SqliteAccountRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def facts(self) -> tuple[AccountFacts, ...]:
        return tuple(
            Account(AccountId(row["id"]), row["balance_cents"]).facts()
            for row in self._connection.execute("SELECT id, balance_cents FROM accounts")
        )
