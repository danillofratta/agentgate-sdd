from datetime import datetime
from typing import Any

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_attempted_event import OperationAttemptedEvent
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_failed_event import OperationFailedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.audit_record import AuditRecord
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint
from agentgate.domain.value_objects.tool import Tool


def _hydrate(row: Any) -> AuditRecord:
    if row["event_type"] in {"OPERATION_ATTEMPTED", "OPERATION_FAILED"}:
        identity = (
            OperationId(row["operation_id"]),
            PrincipalId(row["principal_id"]),
            Tool(row["tool"]),
            RequestFingerprint(row["fingerprint"]),
            PolicyVersion(row["policy_version"]),
            datetime.fromisoformat(row["occurred_at"]),
        )
        if row["approver_id"] is not None:
            raise StorageUnavailable
        if row["event_type"] == "OPERATION_ATTEMPTED":
            if row["decision"] != "ALLOW" or row["reason"] != "EXECUTION_ATTEMPT":
                raise StorageUnavailable
            return AuditRecord(row["id"], OperationAttemptedEvent(*identity, row["attempt"]))
        if row["reason"] != "EXECUTION_" + row["decision"] or row["attempt"] is not None:
            raise StorageUnavailable
        return AuditRecord(
            row["id"], OperationFailedEvent(*identity, OperationState(row["decision"]))
        )
    if row["event_type"] in {"OPERATION_EXECUTED", "OPERATION_DISPATCHED"}:
        succeeded = row["event_type"] == "OPERATION_EXECUTED"
        if (
            row["decision"] != ("SUCCEEDED" if succeeded else "ALLOW")
            or row["reason"] != ("EXECUTION_SUCCEEDED" if succeeded else "DISPATCH_AUTHORIZED")
            or row["approver_id"] is not None
        ):
            raise StorageUnavailable
        event_type = OperationExecutedEvent if succeeded else OperationDispatchedEvent
        return AuditRecord(
            row["id"],
            event_type(
                OperationId(row["operation_id"]),
                PrincipalId(row["principal_id"]),
                Tool(row["tool"]),
                RequestFingerprint(row["fingerprint"]),
                PolicyVersion(row["policy_version"]),
                datetime.fromisoformat(row["occurred_at"]),
            ),
        )
    if row["event_type"] == "APPROVAL_EXPIRED":
        if (
            row["decision"] != "EXPIRED"
            or row["reason"] != "APPROVAL_EXPIRED"
            or row["approver_id"] is not None
        ):
            raise StorageUnavailable
        return AuditRecord(
            row["id"],
            ApprovalExpiredEvent(
                OperationId(row["operation_id"]),
                PrincipalId(row["principal_id"]),
                Tool(row["tool"]),
                RequestFingerprint(row["fingerprint"]),
                PolicyVersion(row["policy_version"]),
                datetime.fromisoformat(row["occurred_at"]),
            ),
        )
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
