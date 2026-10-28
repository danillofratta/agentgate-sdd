import json
from typing import Annotated

from fastapi import APIRouter, Depends

from agentgate.dependencies import get_get_operation_handler, get_principal
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.get_operation.models import ApprovalResponse, OperationResponse
from agentgate.features.get_operation.query import GetOperationQuery

router = APIRouter()


@router.get("/operations/{id}", response_model=OperationResponse)
def get_operation(
    id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[GetOperationHandler, Depends(get_get_operation_handler)],
) -> OperationResponse:
    snapshot = handler.handle(GetOperationQuery(principal, OperationId(id)))
    operation = snapshot.operation
    stored = snapshot.result
    result: dict[str, str | int] | None = None
    if isinstance(stored, BalanceResult):
        result = {
            "account_id": stored.account_id.value,
            "balance_cents": stored.balance_cents,
            "currency": stored.currency,
        }
    elif stored is not None:
        result = {
            "source_account_id": stored.source_account_id.value,
            "destination_account_id": stored.destination_account_id.value,
            "amount_cents": stored.amount.cents,
            "currency": stored.amount.currency,
        }
    authorization = operation.execution_authorization
    return OperationResponse(
        id=operation.id.value,
        state=operation.state.value,
        tool=operation.request.tool.value,
        arguments=json.loads(operation.request.canonical_json())["arguments"],
        decision=operation.policy.decision.value,
        reason=operation.policy.reason.value,
        policy_version=operation.policy.version.value,
        created_at=operation.created_at,
        approval=None
        if snapshot.approval is None
        else ApprovalResponse(
            state=snapshot.approval.state.value,
            created_at=snapshot.approval.created_at,
            expires_at=snapshot.approval.expires_at,
        ),
        result=result,
        effective_decision=None if authorization is None else authorization.decision.value,
        effective_reason=None if authorization is None else authorization.reason.value,
    )
