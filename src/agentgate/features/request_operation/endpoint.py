import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from agentgate.dependencies import get_handler, get_principal
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.features.request_operation.command import (
    RequestOperationCommand,
)
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)
from agentgate.features.request_operation.models import BalanceRequest, OperationBody

router = APIRouter()


@router.post("/operations")
def request_operation(
    payload: OperationBody,
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[RequestOperationHandler, Depends(get_handler)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"\A[A-Za-z0-9_-]{1,64}\z")
    ],
) -> JSONResponse:
    arguments: BalanceArguments | TransferArguments
    if isinstance(payload, BalanceRequest):
        arguments = BalanceArguments(AccountId(payload.arguments.account_id))
    else:
        args = payload.arguments
        arguments = TransferArguments(
            AccountId(args.source_account_id),
            AccountId(args.destination_account_id),
            Money(args.amount_cents, args.currency),
        )
    result = handler.handle(
        RequestOperationCommand(
            principal, IdempotencyKey(idempotency_key), OperationRequest(arguments)
        )
    )
    operation = result.operation
    return JSONResponse(
        status_code=201 if result.created else 200,
        content={
            "id": operation.id.value,
            "simulation": True,
            "state": operation.state.value,
            "tool": operation.request.tool.value,
            "arguments": json.loads(operation.request.canonical_json())["arguments"],
            "decision": operation.policy.decision.value,
            "reason": operation.policy.reason.value,
            "policy_version": operation.policy.version.value,
            "created_at": operation.created_at.isoformat(),
            "result": None,
        },
    )
