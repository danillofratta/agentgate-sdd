from typing import Any

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from agentgate.application.exceptions.agent_unavailable import AgentUnavailable


class SdkAgentMcpGateway:
    """Actual official MCP SDK client. Each bounded exchange owns and closes its session."""

    def __init__(self, token: str, url: str = "http://mcp:8000/mcp") -> None:
        if url not in {"http://mcp:8000/mcp", "http://127.0.0.1:8002/mcp"}:
            raise ValueError("AGENTGATE_CHAT_MCP_URL")
        self._token, self._url = token, url

    async def _exchange(self, name: str | None, arguments: dict[str, Any]) -> Any:
        try:
            async with httpx2.AsyncClient(
                headers={
                    "Authorization": "Bearer " + self._token,
                    "Host": "127.0.0.1:8000"
                    if self._url.startswith("http://mcp:")
                    else "127.0.0.1:8002",
                },
                timeout=6,
                trust_env=False,
                follow_redirects=False,
            ) as http:
                async with Client(
                    streamable_http_client(self._url, http_client=http),
                    mode="legacy",
                    cache=None,
                    read_timeout_seconds=6,
                ) as client:
                    if name is None:
                        return await client.list_tools()
                    return await client.call_tool(name, arguments)
        except Exception:
            raise AgentUnavailable() from None

    async def discover(self) -> list[dict[str, Any]]:
        result = await self._exchange(None, {})
        return [{"name": tool.name, "parameters": tool.input_schema} for tool in result.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._exchange(name, arguments)
        raw = result.structured_content
        if not isinstance(raw, dict):
            raise AgentUnavailable()
        return raw
