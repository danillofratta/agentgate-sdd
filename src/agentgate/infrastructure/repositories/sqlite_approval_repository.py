import sqlite3
from dataclasses import replace
from datetime import datetime

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.infrastructure.repositories.operation_mapper import hydrate


class SqliteApprovalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, operation_id: OperationId) -> Approval | None:
        try:
            row = self._connection.execute(
                "SELECT * FROM approvals WHERE operation_id=?", (operation_id.value,)
            ).fetchone()
            if row is None:
                return None
            operation_row = self._connection.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id.value,)
            ).fetchone()
            if operation_row is None:
                raise StorageUnavailable
            # Rebuild snapshots through domain transitions, without executing commands.
            operation = hydrate(operation_row, stored_state=True)
            pending = replace(operation)
            approval = Approval(pending)
            if (
                row["principal_id"] != pending.principal_id.value
                or row["fingerprint"] != pending.request.fingerprint.value
                or row["policy_version"] != pending.policy.version.value
                or datetime.fromisoformat(row["created_at"]) != pending.created_at
                or datetime.fromisoformat(row["expires_at"]) != approval.expires_at
            ):
                raise StorageUnavailable
            if row["decision"] is None:
                if any(row[key] is not None for key in ("decision", "approver_id", "decided_at")):
                    raise StorageUnavailable
            else:
                approval = approval.decide(
                    Principal(
                        PrincipalId(row["approver_id"]), Role.APPROVER, frozenset(), frozenset()
                    ),
                    ApprovalDecision(row["decision"]),
                    datetime.fromisoformat(row["decided_at"]),
                )
            if row["status"] == "EXPIRED":
                approval = approval.expire(approval.expires_at)
            expected_operation = approval.operation
            if row["status"] == "CONSUMED":
                approval = approval.consume(
                    approval.operation,
                    approval.operation.policy.version,
                    datetime.fromisoformat(row["consumed_at"]),
                    principal=Principal(
                        approval.operation.principal_id, Role.AGENT, frozenset(), frozenset()
                    ),
                )
                if operation.execution_authorization is None:
                    raise StorageUnavailable
                expected_operation = approval.operation.authorize_execution(
                    operation.execution_authorization
                ).transition(OperationState.SUCCEEDED)
            if operation.state in (OperationState.FAILED, OperationState.TIMED_OUT):
                expected_operation = expected_operation.transition(operation.state)
            if approval.state.value != row["status"] or expected_operation != operation:
                raise StorageUnavailable
            return approval
        except (ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None

    def save_consumption(self, approval: Approval) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if approval.state != ApprovalState.CONSUMED or approval.consumed_at is None:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        operation = approval.operation
        cursor = self._connection.execute(
            """UPDATE approvals SET status='CONSUMED', consumed_at=?
               WHERE operation_id=? AND status='GRANTED' AND consumed_at IS NULL
               AND principal_id=? AND fingerprint=? AND policy_version=?
               AND created_at=? AND expires_at=? AND decision='APPROVE'
               AND approver_id=? AND decided_at=?""",
            (
                approval.consumed_at.isoformat(),
                operation.id.value,
                operation.principal_id.value,
                operation.request.fingerprint.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                approval.expires_at.isoformat(),
                None if approval.approver_id is None else approval.approver_id.value,
                None if approval.decided_at is None else approval.decided_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def save_decision(self, approval: Approval) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if approval.state not in {ApprovalState.GRANTED, ApprovalState.REJECTED}:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        event = approval.decided_event()
        cursor = self._connection.execute(
            """UPDATE approvals SET status=?, decision=?, approver_id=?, decided_at=?
               WHERE operation_id=? AND status='PENDING' AND decision IS NULL
               AND principal_id=? AND fingerprint=? AND policy_version=?
               AND created_at=? AND expires_at=?""",
            (
                approval.state.value,
                event.decision.value,
                event.approver_id.value,
                event.occurred_at.isoformat(),
                event.operation_id.value,
                event.principal_id.value,
                event.fingerprint.value,
                event.policy_version.value,
                approval.operation.created_at.isoformat(),
                approval.expires_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def add(self, approval: Approval) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
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

    def save_expiry(self, approval: Approval) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if approval.state != ApprovalState.EXPIRED:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        operation = approval.operation
        cursor = self._connection.execute(
            """UPDATE approvals SET status='EXPIRED'
               WHERE operation_id=? AND status=? AND decision IS ? AND approver_id IS ?
               AND decided_at IS ? AND principal_id=? AND fingerprint=? AND policy_version=?
               AND created_at=? AND expires_at=?""",
            (
                operation.id.value,
                "PENDING" if approval.decision is None else "GRANTED",
                None if approval.decision is None else approval.decision.value,
                None if approval.approver_id is None else approval.approver_id.value,
                None if approval.decided_at is None else approval.decided_at.isoformat(),
                operation.principal_id.value,
                operation.request.fingerprint.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                approval.expires_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
