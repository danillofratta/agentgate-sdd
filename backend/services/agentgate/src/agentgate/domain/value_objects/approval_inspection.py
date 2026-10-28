from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.enums.approval_state import ApprovalState


@dataclass(frozen=True)
class ApprovalInspection:
    """Persisted approval metadata; reading it does not derive or persist expiry."""

    state: ApprovalState
    created_at: datetime
    expires_at: datetime
