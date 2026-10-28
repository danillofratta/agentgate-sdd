from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class BalanceArguments(StrictBody):
    account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]


class TransferArguments(StrictBody):
    source_account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]
    destination_account_id: Annotated[str, Field(pattern=r"\Aacct-[a-z0-9]{1,32}\z")]
    amount_cents: Annotated[int, Field(ge=1, le=2**63 - 1)]
    currency: Literal["USD"]

    @model_validator(mode="after")
    def distinct_accounts(self) -> Self:
        if self.source_account_id == self.destination_account_id:
            raise ValueError("INVALID_INPUT")
        return self


class Submission(StrictBody):
    tool_name: Literal["get_balance", "simulate_transfer"]
    arguments: BalanceArguments | TransferArguments
    idempotency_key: Annotated[str, Field(pattern=r"\A[A-Za-z0-9_-]{1,64}\z")]

    @model_validator(mode="after")
    def matching_arguments(self) -> Self:
        if (self.tool_name == "get_balance") != isinstance(self.arguments, BalanceArguments):
            raise ValueError("INVALID_INPUT")
        return self


class OperationReference(StrictBody):
    operation_id: Annotated[
        str, Field(pattern=r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z")
    ]
