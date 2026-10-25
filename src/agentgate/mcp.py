from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from agentgate.dependencies import build_mcp_gateway, mcp_token
from agentgate.features.mcp_ingress.endpoint import build_server, health_route
from agentgate.transport.body_limit import BodyLimit
from agentgate.transport.mcp_envelope import McpEnvelope
from agentgate.transport.mcp_security import HOSTS, ORIGINS, McpSecurity


def create_app() -> Starlette:
    token = mcp_token()
    client, gateway = build_mcp_gateway()
    server = build_server(gateway)
    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=16 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(HOSTS),
            allowed_origins=list(ORIGINS),
        ),
        custom_starlette_routes=[health_route],
    )
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        async with client, sdk_lifespan(application):
            yield

    app.router.lifespan_context = lifespan
    app.add_middleware(McpEnvelope)
    app.add_middleware(BodyLimit)
    app.add_middleware(McpSecurity, token=token)
    return app
