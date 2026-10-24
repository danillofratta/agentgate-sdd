import sqlite3

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class SqliteAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(
        self,
        event: OperationRequestedEvent
        | ApprovalDecidedEvent
        | ApprovalExpiredEvent
        | OperationExecutedEvent
        | OperationDispatchedEvent,
    ) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if isinstance(event, (OperationExecutedEvent, OperationDispatchedEvent)):
            succeeded = isinstance(event, OperationExecutedEvent)
            self._connection.execute(
                """INSERT INTO audit_events(operation_id, principal_id, tool, decision,
                   reason, policy_version, occurred_at, event_type, fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event.operation_id.value,
                    event.principal_id.value,
                    event.tool.value,
                    "SUCCEEDED" if succeeded else "ALLOW",
                    "EXECUTION_SUCCEEDED" if succeeded else "DISPATCH_AUTHORIZED",
                    event.policy_version.value,
                    event.occurred_at.isoformat(),
                    "OPERATION_EXECUTED" if succeeded else "OPERATION_DISPATCHED",
                    event.fingerprint.value,
                ),
            )
            return
        if isinstance(event, ApprovalExpiredEvent):
            self._connection.execute(
                """INSERT INTO audit_events(operation_id, principal_id, tool, decision,
                   reason, policy_version, occurred_at, event_type, fingerprint)
                   VALUES (?,?,?,'EXPIRED','APPROVAL_EXPIRED',?,?,'APPROVAL_EXPIRED',?)""",
                (
                    event.operation_id.value,
                    event.principal_id.value,
                    event.tool.value,
                    event.policy_version.value,
                    event.occurred_at.isoformat(),
                    event.fingerprint.value,
                ),
            )
            return
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
