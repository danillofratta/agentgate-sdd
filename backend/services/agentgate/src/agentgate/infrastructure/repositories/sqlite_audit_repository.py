import sqlite3
from datetime import datetime

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.operation import Operation
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_attempted_event import OperationAttemptedEvent
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_failed_event import OperationFailedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.infrastructure.repositories.operation_mapper import hydrate


class SqliteAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append_attempt(
        self, operation: Operation, occurred_at: datetime
    ) -> OperationAttemptedEvent:
        if not self._connection.in_transaction or operation.state != OperationState.READY:
            raise StorageUnavailable
        row = self._connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation.id.value,)
        ).fetchone()
        if row is None or hydrate(row, stored_state=True) != operation:
            raise StorageUnavailable
        number = self._connection.execute(
            "SELECT COALESCE(MAX(attempt),0)+1 FROM audit_events WHERE operation_id=?",
            (operation.id.value,),
        ).fetchone()[0]
        event = OperationAttemptedEvent(
            operation.id,
            operation.principal_id,
            operation.request.tool,
            operation.request.fingerprint,
            operation.policy.version,
            occurred_at,
            number,
        )
        if occurred_at < operation.created_at:
            raise StorageUnavailable
        self._connection.execute(
            """INSERT INTO audit_events(operation_id, principal_id, tool, decision, reason,
               policy_version, occurred_at, event_type, fingerprint, attempt)
               VALUES (?,?,?,'ALLOW','EXECUTION_ATTEMPT',?,?,'OPERATION_ATTEMPTED',?,?)""",
            (
                event.operation_id.value,
                event.principal_id.value,
                event.tool.value,
                event.policy_version.value,
                event.occurred_at.isoformat(),
                event.fingerprint.value,
                event.attempt,
            ),
        )
        return event

    def append(
        self,
        event: OperationRequestedEvent
        | ApprovalDecidedEvent
        | ApprovalExpiredEvent
        | OperationExecutedEvent
        | OperationAttemptedEvent
        | OperationFailedEvent
        | OperationDispatchedEvent,
    ) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if isinstance(event, OperationAttemptedEvent):
            # Numbers and identity can only be allocated from authoritative storage.
            raise StorageUnavailable
        if isinstance(event, OperationFailedEvent):
            row = self._connection.execute(
                "SELECT * FROM operations WHERE id=?", (event.operation_id.value,)
            ).fetchone()
            if row is None:
                raise StorageUnavailable
            operation = hydrate(row, stored_state=True)
            if (
                operation.state != event.state
                or operation.principal_id != event.principal_id
                or operation.request.fingerprint != event.fingerprint
                or operation.request.tool != event.tool
                or operation.policy.version != event.policy_version
            ):
                raise StorageUnavailable
            self._connection.execute(
                """INSERT INTO audit_events(operation_id, principal_id, tool, decision, reason,
                   policy_version, occurred_at, event_type, fingerprint)
                   VALUES (?,?,?,?,?,?,?,'OPERATION_FAILED',?)""",
                (
                    event.operation_id.value,
                    event.principal_id.value,
                    event.tool.value,
                    event.state.value,
                    "EXECUTION_" + event.state.value,
                    event.policy_version.value,
                    event.occurred_at.isoformat(),
                    event.fingerprint.value,
                ),
            )
            return
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
