from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ExecutionResponse(BaseModel):
    id: str
    simulation: Literal[True] = True
    state: str
    tool: str
    decision: str
    reason: str
    policy_version: str
    created_at: datetime
    result: dict[str, str | int] | None
    effective_decision: str | None
    effective_reason: str | None
