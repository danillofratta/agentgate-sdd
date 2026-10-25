import json

from mcp_types import jsonrpc_message_adapter
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class McpEnvelope:
    """Validate bounded wire envelopes before legacy SDK errors can echo raw input."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/mcp":
            await self.app(scope, receive, send)
            return
        body = await Request(scope, receive).body()
        try:
            raw = json.loads(body)
            if (
                isinstance(raw, dict)
                and "id" in raw
                and (not isinstance(raw["id"], (str, int)) or isinstance(raw["id"], bool))
            ):
                raise ValueError("INVALID_INPUT")
            jsonrpc_message_adapter.validate_json(body, by_name=False)
        except (ValidationError, ValueError, RecursionError):
            await JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "INVALID_INPUT"},
                },
                status_code=400,
            )(scope, receive, send)
            return
        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, buffered_receive, send)
