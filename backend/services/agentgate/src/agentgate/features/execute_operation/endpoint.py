from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.dependencies import get_execute_operation_handler, get_principal
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.execute_operation.models import ExecutionResponse

router = APIRouter()


@router.post("/operations/{id}/execute", response_model=ExecutionResponse)
async def execute_operation(
    id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[ExecuteOperationHandler, Depends(get_execute_operation_handler)],
) -> ExecutionResponse:
    if await request.body():
        raise InvariantViolation("INVALID_INPUT")
    command = ExecuteOperationCommand(principal, OperationId(id))
    try:
        outcome = await run_in_threadpool(handler.handle, command)
    except ExecutionUnavailable:
        outcome = await run_in_threadpool(handler.terminal_result, command)
    operation = outcome.operation
    stored = outcome.result
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
    return ExecutionResponse(
        id=operation.id.value,
        state=operation.state.value,
        tool=operation.request.tool.value,
        decision=operation.policy.decision.value,
        reason=operation.policy.reason.value,
        policy_version=operation.policy.version.value,
        created_at=operation.created_at,
        result=result,
        effective_decision=None if authorization is None else authorization.decision.value,
        effective_reason=None if authorization is None else authorization.reason.value,
    )
