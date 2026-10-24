from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class BalanceBody(StrictBody):
    account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]


class TransferBody(StrictBody):
    source_account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]
    destination_account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]
    amount_cents: Annotated[int, Field(ge=1, le=2**63 - 1)]
    currency: Literal["USD"]

    @model_validator(mode="after")
    def distinct_accounts(self) -> Self:
        if self.source_account_id == self.destination_account_id:
            raise ValueError("SAME_ACCOUNT_TRANSFER")
        return self


class BalanceRequest(StrictBody):
    tool: Literal["get_balance"]
    arguments: BalanceBody


class TransferRequest(StrictBody):
    tool: Literal["simulate_transfer"]
    arguments: TransferBody


OperationBody = Annotated[BalanceRequest | TransferRequest, Field(discriminator="tool")]
