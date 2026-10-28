import asyncio
import json
from typing import Any

import httpx

from agentgate.application.exceptions.agent_unavailable import AgentUnavailable
from agentgate.infrastructure.security.llm_settings import LlmSettings


class OpenaiChatGateway:
    """OpenAI-compatible wire contract, no SDK retries, fixed HTTPS origins and no logging."""

    def __init__(self, settings: LlmSettings, protected: tuple[str, ...] = ()) -> None:
        self._settings = settings
        self._protected = (settings.api_key, *protected)
        self._verified = False
        self._verification_lock = asyncio.Lock()

    async def verify_tools(self) -> None:
        async with self._verification_lock:
            if self._verified:
                return
            # A harmless forced function establishes capability for the configured model/key.
            tool = {
                "type": "function",
                "function": {
                    "name": "capability_probe",
                    "description": "No-op capability check; no effects.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            }
            result = await self.complete(
                [{"role": "user", "content": "Call capability_probe with empty arguments."}],
                [tool],
                "capability_probe",
            )
            try:
                calls = result["tool_calls"]
                if (
                    len(calls) != 1
                    or calls[0]["function"]["name"] != "capability_probe"
                    or json.loads(calls[0]["function"]["arguments"]) != {}
                ):
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise AgentUnavailable() from None
            self._verified = True

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        required: str | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": required}}
            if required
            else "auto",
            "parallel_tool_calls": False,
            "max_completion_tokens": settings.max_tokens,
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.timeout, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST",
                    settings.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + settings.api_key},
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        raise AgentUnavailable()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise AgentUnavailable()
            decoded = json.loads(body)
            if decoded["choices"][0].get("finish_reason") not in {"stop", "tool_calls"}:
                raise AgentUnavailable()
            result = decoded["choices"][0]["message"]
            if not isinstance(result, dict):
                raise AgentUnavailable()
            # No provider metadata, reasoning, headers or rejected raw response is retained.
            content = result.get("content")
            if isinstance(content, str):
                for value in self._protected:
                    if value:
                        content = content.replace(value, "[REDACTED]")
            return {"content": content, "tool_calls": result.get("tool_calls") or []}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, RecursionError):
            raise AgentUnavailable() from None
