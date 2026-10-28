import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HOSTS = ("127.0.0.1:8002", "localhost:8002", "127.0.0.1:8000")
ORIGINS = ("http://127.0.0.1:8002", "http://localhost:8002")


class McpSecurity:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._authorization = "Bearer " + token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        # Reject before SDK logging can echo an attacker-controlled Host or Origin.
        if (
            len(headers.getlist("host")) != 1
            or headers.get("host") not in HOSTS
            or len(headers.getlist("origin")) > 1
            or ("origin" in headers and headers["origin"] not in ORIGINS)
            or headers.get("sec-fetch-site") == "cross-site"
        ):
            await JSONResponse({"error": "FORBIDDEN"}, status_code=403)(scope, receive, send)
            return
        if scope["path"] != "/health":
            values = headers.getlist("authorization")
            if len(values) != 1 or not hmac.compare_digest(
                values[0].encode(), self._authorization.encode()
            ):
                await JSONResponse(
                    {"error": "UNAUTHENTICATED"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)
