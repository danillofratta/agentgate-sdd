from typing import Annotated

from fastapi import APIRouter, Depends, Query

from agentgate.dependencies import get_list_audit_handler, get_principal
from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.list_audit.models import AuditEventResponse, AuditPageResponse
from agentgate.features.list_audit.query import ListAuditQuery

router = APIRouter()


@router.get("/audit", response_model=AuditPageResponse)
def list_audit(
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[ListAuditHandler, Depends(get_list_audit_handler)],
    after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditPageResponse:
    result = handler.handle(ListAuditQuery(principal, after, limit))
    return AuditPageResponse(
        events=[
            AuditEventResponse(
                id=record.id,
                operation_id=record.event.operation_id.value,
                principal_id=record.event.principal_id.value,
                tool=record.event.tool.value,
                decision=(
                    "SUCCEEDED"
                    if isinstance(record.event, OperationExecutedEvent)
                    else "ALLOW"
                    if isinstance(record.event, OperationDispatchedEvent)
                    else "EXPIRED"
                    if isinstance(record.event, ApprovalExpiredEvent)
                    else record.event.policy.decision.value
                    if isinstance(record.event, OperationRequestedEvent)
                    else record.event.decision.value
                ),
                reason=(
                    "EXECUTION_SUCCEEDED"
                    if isinstance(record.event, OperationExecutedEvent)
                    else "DISPATCH_AUTHORIZED"
                    if isinstance(record.event, OperationDispatchedEvent)
                    else "APPROVAL_EXPIRED"
                    if isinstance(record.event, ApprovalExpiredEvent)
                    else record.event.policy.reason.value
                    if isinstance(record.event, OperationRequestedEvent)
                    else "HUMAN_"
                    + ("APPROVED" if record.event.decision.value == "APPROVE" else "REJECTED")
                ),
                policy_version=(
                    record.event.policy.version.value
                    if isinstance(record.event, OperationRequestedEvent)
                    else record.event.policy_version.value
                ),
                occurred_at=record.event.occurred_at,
                event_type=(
                    "OPERATION_EXECUTED"
                    if isinstance(record.event, OperationExecutedEvent)
                    else "OPERATION_DISPATCHED"
                    if isinstance(record.event, OperationDispatchedEvent)
                    else "APPROVAL_EXPIRED"
                    if isinstance(record.event, ApprovalExpiredEvent)
                    else "OPERATION_REQUESTED"
                    if isinstance(record.event, OperationRequestedEvent)
                    else "APPROVAL_DECIDED"
                ),
                approver_id=(
                    record.event.approver_id.value
                    if isinstance(record.event, ApprovalDecidedEvent)
                    else None
                ),
                fingerprint=(
                    None
                    if isinstance(record.event, OperationRequestedEvent)
                    else record.event.fingerprint.value
                ),
            )
            for record in result.events
        ],
        next_after=result.next_after,
    )
