import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.audit_record import AuditRecord
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint
from agentgate.domain.value_objects.tool import Tool


def _hydrate(row: sqlite3.Row) -> AuditRecord:
    if row["event_type"] == "APPROVAL_DECIDED":
        return AuditRecord(
            row["id"],
            ApprovalDecidedEvent(
                OperationId(row["operation_id"]),
                PrincipalId(row["principal_id"]),
                PrincipalId(row["approver_id"]),
                RequestFingerprint(row["fingerprint"]),
                PolicyVersion(row["policy_version"]),
                ApprovalDecision(row["decision"]),
                datetime.fromisoformat(row["occurred_at"]),
                Tool(row["tool"]),
            ),
        )
    if row["event_type"] != "OPERATION_REQUESTED":
        raise StorageUnavailable
    return AuditRecord(
        row["id"],
        OperationRequestedEvent(
            OperationId(row["operation_id"]),
            PrincipalId(row["principal_id"]),
            Tool(row["tool"]),
            PolicyDecision(
                Decision(row["decision"]),
                Reason(row["reason"]),
                PolicyVersion(row["policy_version"]),
            ),
            datetime.fromisoformat(row["occurred_at"]),
        ),
    )


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
                       policy_version, occurred_at, event_type, approver_id, fingerprint
                       FROM audit_events
                       WHERE id > ? ORDER BY id ASC LIMIT ?""",
                    (page.after, page.limit),
                ).fetchall()
                return tuple(_hydrate(row) for row in rows)
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
