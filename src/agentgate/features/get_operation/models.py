from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApprovalResponse(BaseModel):
    state: str
    created_at: datetime
    expires_at: datetime


class OperationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    simulation: Literal[True] = True
    state: str
    tool: str
    arguments: dict[str, str | int]
    decision: str
    reason: str
    policy_version: str
    created_at: datetime
    approval: ApprovalResponse | None
    result: dict[str, str | int] | None
    effective_decision: str | None
    effective_reason: str | None
