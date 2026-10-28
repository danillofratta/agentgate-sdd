from contextlib import closing

import psycopg

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.account import Account
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.infrastructure.persistence.postgres_database import begin_read, connect


class PostgresAccountReadRepository:
    def __init__(self, database: str) -> None:
        self._database = database

    def facts(self) -> tuple[AccountFacts, ...]:
        try:
            with closing(connect(self._database)) as connection:
                begin_read(connection)
                rows = connection.execute("SELECT id, balance_cents FROM accounts ORDER BY id")
                return tuple(
                    AccountFacts(AccountId(row["id"]), row["balance_cents"]) for row in rows
                )
        except (psycopg.Error, ValueError, TypeError, KeyError):
            raise StorageUnavailable from None

    def save(self, account: Account) -> None:
        raise StorageUnavailable
