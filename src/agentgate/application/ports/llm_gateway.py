from typing import Any, Protocol


class LlmGateway(Protocol):
    async def verify_tools(self) -> None: ...

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        required: str | None = None,
    ) -> dict[str, Any]: ...
