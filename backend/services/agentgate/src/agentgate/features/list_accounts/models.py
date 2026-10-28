from pydantic import BaseModel


class AccountResponse(BaseModel):
    id: str
    balance_cents: int
    currency: str = "USD"
