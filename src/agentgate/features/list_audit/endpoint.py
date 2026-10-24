from typing import Annotated

from fastapi import APIRouter, Depends, Query

from agentgate.dependencies import get_list_audit_handler, get_principal
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
                decision=record.event.policy.decision.value,
                reason=record.event.policy.reason.value,
                policy_version=record.event.policy.version.value,
                occurred_at=record.event.occurred_at,
            )
            for record in result.events
        ],
        next_after=result.next_after,
    )
