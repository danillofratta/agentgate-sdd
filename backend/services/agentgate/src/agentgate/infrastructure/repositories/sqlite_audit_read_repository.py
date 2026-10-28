import sqlite3
from contextlib import closing
from pathlib import Path

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.audit_record import AuditRecord
from agentgate.infrastructure.repositories.audit_mapper import _hydrate


class SqliteAuditReadRepository:
    def __init__(self, path: str) -> None:
        self._uri = Path(path).resolve().as_uri() + "?mode=ro"

    def list(self, page: AuditPage) -> tuple[AuditRecord, ...]:
        # Validate before SQL binding even when called without an HTTP adapter.
        AuditPage(page.after, page.limit)
        try:
            with closing(
                sqlite3.connect(self._uri, uri=True, timeout=0.05, isolation_level=None)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                rows = connection.execute(
                    """SELECT id, operation_id, principal_id, tool, decision, reason,
                       policy_version, occurred_at, event_type, approver_id, fingerprint, attempt
                       FROM audit_events
                       WHERE id > ? ORDER BY id ASC LIMIT ?""",
                    (page.after, page.limit),
                ).fetchall()
                return tuple(_hydrate(row) for row in rows)
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
