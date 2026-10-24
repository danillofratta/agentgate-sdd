import sqlite3

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class SqliteAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, event: OperationRequestedEvent | ApprovalDecidedEvent) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if isinstance(event, ApprovalDecidedEvent):
            self._connection.execute(
                """INSERT INTO audit_events(operation_id, principal_id, tool, decision,
                   reason, policy_version, occurred_at, event_type, approver_id, fingerprint)
                   VALUES (?,?,?,?,?,?,?,'APPROVAL_DECIDED',?,?)""",
                (
                    event.operation_id.value,
                    event.principal_id.value,
                    event.tool.value,
                    event.decision.value,
                    "HUMAN_APPROVED" if event.decision.value == "APPROVE" else "HUMAN_REJECTED",
                    event.policy_version.value,
                    event.occurred_at.isoformat(),
                    event.approver_id.value,
                    event.fingerprint.value,
                ),
            )
            return
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
