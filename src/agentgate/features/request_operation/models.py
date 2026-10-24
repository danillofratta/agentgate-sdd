from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class BalanceBody(StrictBody):
    account_id: Annotated[str, Field(pattern="^acct-[a-z0-9]{1,32}$")]


class TransferBody(StrictBody):
    source_account_id: Annotated[str, Field(pattern="^acct-[a-z0-9]{1,32}$")]
    destination_account_id: Annotated[str, Field(pattern="^acct-[a-z0-9]{1,32}$")]
    amount_cents: Annotated[int, Field(ge=1, le=2**63 - 1)]
    currency: Literal["USD"]


class BalanceRequest(StrictBody):
    tool: Literal["get_balance"]
    arguments: BalanceBody


class TransferRequest(StrictBody):
    tool: Literal["simulate_transfer"]
    arguments: TransferBody


OperationBody = Annotated[BalanceRequest | TransferRequest, Field(discriminator="tool")]
