import sqlite3

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.account import Account
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId


class SqliteAccountRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, account: Account) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        cursor = self._connection.execute(
            "UPDATE accounts SET balance_cents=? WHERE id=?",
            (account.balance_cents, account.id.value),
        )
        if cursor.rowcount != 1:
            raise StorageUnavailable

    def facts(self) -> tuple[AccountFacts, ...]:
        return tuple(
            Account(AccountId(row["id"]), row["balance_cents"]).facts()
            for row in self._connection.execute("SELECT id, balance_cents FROM accounts")
        )
