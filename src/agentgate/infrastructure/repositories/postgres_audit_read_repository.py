from contextlib import closing

import psycopg

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.audit_record import AuditRecord
from agentgate.infrastructure.persistence.postgres_database import begin_read, connect
from agentgate.infrastructure.repositories.audit_mapper import _hydrate


class PostgresAuditReadRepository:
    def __init__(self, database: str) -> None:
        self._database = database

    def list(self, page: AuditPage) -> tuple[AuditRecord, ...]:
        AuditPage(page.after, page.limit)
        try:
            with closing(connect(self._database)) as connection:
                begin_read(connection)
                rows = connection.execute(
                    "SELECT * FROM audit_events WHERE id>%s ORDER BY id ASC LIMIT %s",
                    (page.after, page.limit),
                ).fetchall()
                return tuple(_hydrate(row) for row in rows)
        except (psycopg.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
