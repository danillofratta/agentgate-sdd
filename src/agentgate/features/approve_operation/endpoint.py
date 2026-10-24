from typing import Annotated

from fastapi import APIRouter, Depends

from agentgate.dependencies import get_approve_operation_handler, get_principal
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.approve_operation.models import ApprovalBody, ApprovalResponse

router = APIRouter()


@router.post("/operations/{id}/approval", response_model=ApprovalResponse)
def approve_operation(
    id: str,
    payload: ApprovalBody,
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[ApproveOperationHandler, Depends(get_approve_operation_handler)],
) -> ApprovalResponse:
    approval = handler.handle(
        ApproveOperationCommand(principal, OperationId(id), ApprovalDecision(payload.decision))
    ).approval
    return ApprovalResponse(
        id=approval.operation.id.value,
        state=approval.operation.state.value,
        approval_state=approval.state.value,
        decision=approval.operation.policy.decision.value,
        policy_version=approval.operation.policy.version.value,
        approval_decision=payload.decision,
        approver_id=None if approval.approver_id is None else approval.approver_id.value,
        decided_at=approval.decided_at,
        expires_at=approval.expires_at,
    )
