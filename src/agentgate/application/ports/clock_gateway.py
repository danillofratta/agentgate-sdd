from datetime import datetime
from typing import Protocol


class ClockGateway(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...
