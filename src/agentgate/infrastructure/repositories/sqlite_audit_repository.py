import sqlite3

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class SqliteAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, event: OperationRequestedEvent) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        self._connection.execute(
            """INSERT INTO audit_events(operation_id, principal_id, tool, decision, reason,
               policy_version, occurred_at, event_type)
               VALUES (?,?,?,?,?,?,?,'OPERATION_REQUESTED')""",
            (
                event.operation_id.value,
                event.principal_id.value,
                event.tool.value,
                event.policy.decision.value,
                event.policy.reason.value,
                event.policy.version.value,
                event.occurred_at.isoformat(),
            ),
        )
