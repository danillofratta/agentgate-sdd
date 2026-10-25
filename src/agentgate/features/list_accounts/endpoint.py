from typing import Annotated

from fastapi import APIRouter, Depends

from agentgate.dependencies import get_list_accounts_handler, get_principal
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.list_accounts.handler import ListAccountsHandler
from agentgate.features.list_accounts.models import AccountResponse
from agentgate.features.list_accounts.query import ListAccountsQuery

router = APIRouter()


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(
    principal: Annotated[Principal, Depends(get_principal)],
    handler: Annotated[ListAccountsHandler, Depends(get_list_accounts_handler)],
) -> list[AccountResponse]:
    return [
        AccountResponse(id=fact.id.value, balance_cents=fact.balance_cents)
        for fact in handler.handle(ListAccountsQuery(principal))
    ]
