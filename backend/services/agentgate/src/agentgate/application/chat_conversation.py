from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatConversation:
    history: list[dict[str, Any]] = field(default_factory=list)
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: tuple[str, dict[str, Any]] | None = None
