import math
import os
import re
from dataclasses import dataclass, field

from agentgate.infrastructure.security.settings import secret


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 20
    max_tokens: int = 512
    max_calls: int = 6
    max_history: int = 12

    def __post_init__(self) -> None:
        # Fixed trusted provider origins prevent configured key forwarding to arbitrary hosts.
        origins = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1"}
        if self.provider not in origins or self.base_url != origins[self.provider]:
            raise ValueError("AGENTGATE_LLM_PROVIDER")
        if not re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", self.model):
            raise ValueError("AGENTGATE_LLM_MODEL")
        if not self.api_key or any(c.isspace() for c in self.api_key) or len(self.api_key) > 512:
            raise ValueError("AGENTGATE_LLM_API_KEY")
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 60:
            raise ValueError("AGENTGATE_LLM_TIMEOUT")
        if (
            not 64 <= self.max_tokens <= 4096
            or not 1 <= self.max_calls <= 12
            or not 2 <= self.max_history <= 24
        ):
            raise ValueError("AGENTGATE_LLM_LIMITS")

    @classmethod
    def from_environment(cls) -> "LlmSettings | None":
        key = secret("AGENTGATE_LLM_API_KEY")
        if not key:
            return None
        provider = os.environ.get("AGENTGATE_LLM_PROVIDER", "openai")
        default = (
            "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        )
        try:
            return cls(
                provider,
                os.environ.get("AGENTGATE_LLM_BASE_URL") or default,
                os.environ.get("AGENTGATE_LLM_MODEL", ""),
                key,
                float(os.environ.get("AGENTGATE_LLM_TIMEOUT", "20")),
                int(os.environ.get("AGENTGATE_LLM_MAX_TOKENS", "512")),
                int(os.environ.get("AGENTGATE_LLM_MAX_TOOL_CALLS", "6")),
                int(os.environ.get("AGENTGATE_LLM_MAX_HISTORY", "12")),
            )
        except ValueError:
            raise ValueError("AGENTGATE_LLM_CONFIGURATION") from None
