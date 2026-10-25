import sqlite3
from contextlib import closing
from pathlib import Path

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.account import Account
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId


class SqliteAccountReadRepository:
    def __init__(self, path: str) -> None:
        self._uri = Path(path).resolve().as_uri() + "?mode=ro"

    def facts(self) -> tuple[AccountFacts, ...]:
        try:
            with closing(sqlite3.connect(self._uri, uri=True, timeout=0.05)) as connection:
                connection.execute("PRAGMA query_only=ON")
                return tuple(
                    AccountFacts(AccountId(row[0]), row[1])
                    for row in connection.execute(
                        "SELECT id, balance_cents FROM accounts ORDER BY id"
                    )
                )
        except (sqlite3.Error, ValueError, TypeError):
            raise StorageUnavailable from None

    def save(self, account: Account) -> None:
        raise StorageUnavailable
