from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    operation_id: str
    principal_id: str
    tool: str
    decision: str
    reason: str
    policy_version: str
    occurred_at: datetime
    event_type: Literal["OPERATION_REQUESTED", "APPROVAL_DECIDED", "APPROVAL_EXPIRED"] = (
        "OPERATION_REQUESTED"
    )
    approver_id: str | None = None
    fingerprint: str | None = None


class AuditPageResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    events: list[AuditEventResponse]
    next_after: int
    simulation: Literal[True] = True
