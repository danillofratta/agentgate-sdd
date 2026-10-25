import hashlib
import hmac
import re
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class LabSecurity:
    def __init__(self, app: ASGIApp, secret: bytes) -> None:
        self._app = app
        self._secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.decode("latin1"): value.decode("latin1") for key, value in scope["headers"]}
        host = headers.get("host", "")
        origin = headers.get("origin")
        valid = (
            host in {"127.0.0.1:8080", "localhost:8080"}
            and (origin is None or origin == "http://" + host)
            and headers.get("sec-fetch-site", "none") in {"none", "same-origin"}
            and "authorization" not in headers
        )
        if scope["method"] not in {"GET", "HEAD"}:
            cookies = SimpleCookie()
            try:
                cookies.load(headers.get("cookie", ""))
                session = cookies["lab_session"].value
                expected = hmac.new(self._secret, session.encode(), hashlib.sha256).hexdigest()
                valid = (
                    valid
                    and origin == "http://" + host
                    and bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", session))
                    and hmac.compare_digest(expected, headers.get("x-lab-csrf", ""))
                )
            except (KeyError, ValueError):
                valid = False
        if not valid:
            await JSONResponse({"error": "LAB_FORBIDDEN"}, status_code=403)(scope, receive, send)
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; "
                            b"connect-src 'self'; frame-ancestors 'none'; "
                            b"base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
            await send(message)

        await self._app(scope, receive, secured_send)
