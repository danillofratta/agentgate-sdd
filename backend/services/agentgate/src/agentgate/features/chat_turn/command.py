from dataclasses import dataclass


@dataclass(frozen=True)
class ChatTurnCommand:
    session_id: str
    message: str = ""
    action: str = "message"
    operation_id: str | None = None
