from dataclasses import dataclass
from datetime import datetime, timedelta

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.utc import require_utc


@dataclass(frozen=True)
class ApprovalDeadline:
    created_at: datetime

    def __post_init__(self) -> None:
        require_utc(self.created_at)
        try:
            self.created_at + timedelta(seconds=300)
        except OverflowError:
            raise InvariantViolation("INVALID_DEADLINE") from None

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=300)

    def expired(self, now: datetime) -> bool:
        require_utc(now)
        if now < self.created_at:
            raise InvariantViolation("INVALID_APPROVAL_TIME")
        return now >= self.expires_at
