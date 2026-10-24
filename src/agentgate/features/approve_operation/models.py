from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApprovalBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    decision: Literal["APPROVE", "REJECT"]


class ApprovalResponse(BaseModel):
    id: str
    simulation: Literal[True] = True
    state: str
    approval_state: str
    decision: str
    policy_version: str
    approval_decision: str
    approver_id: str | None
    decided_at: datetime | None
    expires_at: datetime
