"""Real SDK framing/HTTP adapter with disposable PostgreSQL, no mocked protocol."""

import asyncio

import httpx
import httpx2
import psycopg
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from agentgate import mcp
from agentgate.dependencies import build_components
from agentgate.infrastructure.gateways.local_mcp_api_gateway import LocalMcpApiGateway
from agentgate.main import create_app


def test_postgres_concurrent_mcp_approval_and_replay(pg_settings, monkeypatch):
    from uuid import uuid4

    async def invoke(client, name, arguments, status=200):
        result = await client.call_tool(name, arguments)
        assert result.is_error == (status >= 400)
        assert result.structured_content["http_status"] == status
        return result.structured_content

    api = create_app(build_components(pg_settings), local=True)
    token = "integration-mcp-F9g2H5j8K1m4N7p0Q3s6T9v2W5x8Y1z4"
    monkeypatch.setenv("AGENTGATE_MCP_ENABLED", "1")
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", token)
    monkeypatch.setenv("AGENTGATE_AGENT_TOKEN", pg_settings.agent_token)

    def gateway():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api")
        return http, LocalMcpApiGateway(http, pg_settings.agent_token)

    monkeypatch.setattr(mcp, "build_mcp_gateway", gateway)

    async def run():
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://127.0.0.1:8002",
                headers={"Authorization": "Bearer " + token},
            ) as http:
                async with Client(
                    streamable_http_client("http://127.0.0.1:8002/mcp", http_client=http),
                    mode="legacy",
                    cache=None,
                ) as client:
                    payload = {
                        "tool_name": "simulate_transfer",
                        "idempotency_key": uuid4().hex,
                        "arguments": {
                            "source_account_id": "acct-alice",
                            "destination_account_id": "acct-bob",
                            "amount_cents": 20000,
                            "currency": "USD",
                        },
                    }
                    submitted = await asyncio.gather(
                        *[client.call_tool("request_operation", payload) for _ in range(4)]
                    )
                    assert sorted(r.structured_content["http_status"] for r in submitted) == [
                        200,
                        200,
                        200,
                        201,
                    ]
                    assert len({r.structured_content["id"] for r in submitted}) == 1
                    ref = {"operation_id": submitted[0].structured_content["id"]}
                    await invoke(client, "execute_operation", ref, 409)
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=api),
                        base_url="http://api",
                    ) as human:
                        response = await human.post(
                            "/operations/" + ref["operation_id"] + "/approval",
                            headers={"Authorization": "Bearer " + pg_settings.approver_token},
                            json={"decision": "APPROVE"},
                        )
                        assert response.status_code == 200
                    results = await asyncio.gather(
                        *[invoke(client, "execute_operation", ref) for _ in range(4)]
                    )
                    assert all(r == results[0] for r in results)
                    assert results[0]["state"] == "SUCCEEDED"
                    await invoke(client, "request_operation", payload)
                    view = await invoke(client, "get_operation", ref)
                    assert view["approval"]["state"] == "CONSUMED"

    asyncio.run(run())
    with psycopg.connect(pg_settings.database) as connection:
        assert connection.execute(
            "SELECT id,balance_cents FROM accounts ORDER BY id"
        ).fetchall() == [
            ("acct-alice", 980000),
            ("acct-bob", 1020000),
        ]
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE event_type='OPERATION_EXECUTED'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM approvals a JOIN operations o ON o.id=a.operation_id "
                "WHERE a.fingerprint=o.fingerprint AND a.policy_version=o.policy_version "
                "AND a.principal_id=o.principal_id AND a.status='CONSUMED'"
            ).fetchone()[0]
            == 1
        )
