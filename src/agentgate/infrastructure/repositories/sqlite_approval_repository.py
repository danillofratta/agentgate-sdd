import sqlite3

from agentgate.domain.entities.approval import Approval


class SqliteApprovalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, approval: Approval) -> None:
        operation = approval.operation
        self._connection.execute(
            """INSERT INTO approvals(operation_id, principal_id, fingerprint, policy_version,
               created_at, expires_at, status) VALUES (?,?,?,?,?,?,'PENDING')""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.request.fingerprint.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                approval.expires_at.isoformat(),
            ),
        )
