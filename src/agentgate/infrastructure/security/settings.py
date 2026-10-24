import hmac
import os
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    agent_token: str = field(repr=False)
    approver_token: str = field(repr=False)
    database: str = "agentgate.sqlite3"

    def __post_init__(self) -> None:
        for name, token in (
            ("AGENTGATE_AGENT_TOKEN", self.agent_token),
            ("AGENTGATE_APPROVER_TOKEN", self.approver_token),
        ):
            if (
                not re.fullmatch("[A-Za-z0-9_-]{32,512}", token)
                or len(set(token)) < 8
                or any(
                    marker in token.lower()
                    for marker in ("sample", "example", "change-me", "placeholder")
                )
            ):
                raise ValueError(name)
        if hmac.compare_digest(self.agent_token, self.approver_token):
            raise ValueError("AGENTGATE_APPROVER_TOKEN")
        if not self.database or self.database == ":memory:":
            raise ValueError("AGENTGATE_DATABASE")

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            os.environ.get("AGENTGATE_AGENT_TOKEN", ""),
            os.environ.get("AGENTGATE_APPROVER_TOKEN", ""),
            os.environ.get("AGENTGATE_DATABASE", "agentgate.sqlite3"),
        )
