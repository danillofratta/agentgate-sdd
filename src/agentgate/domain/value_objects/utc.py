from datetime import datetime, timedelta

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


def require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise InvariantViolation("UTC_REQUIRED")
