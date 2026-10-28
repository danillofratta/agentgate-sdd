from datetime import UTC, datetime
from time import monotonic


class SystemClock:
    def monotonic(self) -> float:
        return monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)
