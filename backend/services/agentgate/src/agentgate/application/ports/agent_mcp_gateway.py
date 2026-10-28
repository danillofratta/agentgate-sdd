from typing import Any, Protocol


class AgentMcpGateway(Protocol):
    async def discover(self) -> list[dict[str, Any]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
