import hmac
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


def secret(name: str) -> str:
    path = os.environ.get(name + "_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            raise ValueError(name) from None
    return os.environ.get(name, "")


@dataclass(frozen=True)
class Settings:
    agent_token: str = field(repr=False)
    approver_token: str = field(repr=False)
    database: str = field(default="agentgate.sqlite3", repr=False)

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
        database = os.environ.get("AGENTGATE_DATABASE", "agentgate.sqlite3")
        if os.environ.get("AGENTGATE_POSTGRES_HOST"):
            password = secret("AGENTGATE_POSTGRES_PASSWORD")
            if not password:
                raise ValueError("AGENTGATE_POSTGRES_PASSWORD")
            database = (
                "postgresql://agentgate:"
                + quote(password, safe="")
                + "@"
                + os.environ["AGENTGATE_POSTGRES_HOST"]
                + "/agentgate"
            )
        return cls(
            secret("AGENTGATE_AGENT_TOKEN"),
            secret("AGENTGATE_APPROVER_TOKEN"),
            database,
        )
