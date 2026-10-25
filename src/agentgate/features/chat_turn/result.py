from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatTurnResult:
    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    operations: list[dict[str, Any]]
    error: str | None = None
    retry_pending: bool = False
