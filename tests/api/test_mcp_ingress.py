import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from agentgate import mcp
from agentgate.dependencies import build_components
from agentgate.infrastructure.gateways.local_mcp_api_gateway import LocalMcpApiGateway
from agentgate.main import create_app
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN

MCP_TOKEN = "test-mcp-F9g2H5j8K1m4N7p0Q3s6T9v2W5x8Y1z4"
BASE = "http://127.0.0.1:8002"


def submission(amount=20000, key=None):
    return {
        "tool_name": "simulate_transfer",
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
        "idempotency_key": key or uuid4().hex,
    }


@pytest.fixture
def environment(settings, monkeypatch, clock):
    monkeypatch.setattr("agentgate.dependencies.SystemClock", lambda: clock)
    api = create_app(build_components(settings), local=True)
    monkeypatch.setenv("AGENTGATE_MCP_ENABLED", "1")
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", MCP_TOKEN)
    monkeypatch.setenv("AGENTGATE_AGENT_TOKEN", AGENT_TOKEN)

    def gateway():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api")
        return client, LocalMcpApiGateway(client, AGENT_TOKEN)

    monkeypatch.setattr(mcp, "build_mcp_gateway", gateway)

    @asynccontextmanager
    async def connect(mode="legacy", headers=None):
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url=BASE,
                headers=headers
                if headers is not None
                else {"Authorization": "Bearer " + MCP_TOKEN},
            ) as http:
                async with Client(
                    streamable_http_client(BASE + "/mcp", http_client=http),
                    mode=mode,
                    cache=None,
                    read_timeout_seconds=5,
                ) as client:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=api),
                        base_url="http://api",
                    ) as api_client:
                        yield client, api_client

    return connect


async def invoke(client, name, arguments, status=200):
    result = await client.call_tool(name, arguments)
    assert result.is_error == (status >= 400)
    assert result.structured_content["http_status"] == status
    return result.structured_content


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_real_protocol_discovery_and_schemas(environment, mode):
    async def run():
        async with environment(mode) as (client, _):
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {
                "request_operation",
                "get_operation",
                "execute_operation",
            }
            schemas = {t.name: t.input_schema for t in tools}
            assert schemas["execute_operation"]["additionalProperties"] is False
            assert set(schemas["execute_operation"]["properties"]) == {"operation_id"}
            assert set(schemas["request_operation"]["properties"]) == {
                "tool_name",
                "arguments",
                "idempotency_key",
            }
            body = await invoke(
                client,
                "request_operation",
                {
                    "tool_name": "get_balance",
                    "arguments": {"account_id": "acct-alice"},
                    "idempotency_key": uuid4().hex,
                },
                201,
            )
            assert body["decision"] == "ALLOW" and body["result"] is None

    asyncio.run(run())


def test_human_approval_binding_replay_and_database_consistency(environment, database):
    async def run():
        async with environment() as (client, api):
            payload = submission()
            pending = await invoke(client, "request_operation", payload, 201)
            assert pending["decision"] == "REQUIRE_APPROVAL" and pending["result"] is None
            ref = {"operation_id": pending["id"]}
            original_view = await invoke(client, "get_operation", ref)
            await invoke(client, "execute_operation", ref, 409)
            await invoke(client, "approve_operation", {**ref, "decision": "APPROVE"}, 422)
            agent_grant = await api.post(
                "/operations/" + pending["id"] + "/approval",
                json={"decision": "APPROVE"},
                headers={"Authorization": "Bearer " + AGENT_TOKEN},
            )
            assert agent_grant.status_code == 403
            grant = await api.post(
                "/operations/" + pending["id"] + "/approval",
                json={"decision": "APPROVE"},
                headers={"Authorization": "Bearer " + APPROVER_TOKEN},
            )
            assert grant.status_code == 200
            first, second = await asyncio.gather(
                invoke(client, "execute_operation", ref),
                invoke(client, "execute_operation", ref),
            )
            assert first == second and first["state"] == "SUCCEEDED"
            assert first["decision"] == "REQUIRE_APPROVAL"
            assert first["effective_reason"] == "HUMAN_APPROVED"
            replay = await invoke(client, "request_operation", payload)
            assert replay["id"] == pending["id"] and replay["result"] == first["result"]
            view = await invoke(client, "get_operation", ref)
            assert view["arguments"] == pending["arguments"]
            assert view["approval"]["expires_at"] == original_view["approval"]["expires_at"]
            await invoke(
                client,
                "request_operation",
                {
                    **payload,
                    "arguments": {**payload["arguments"], "amount_cents": 20001},
                },
                409,
            )
        # Recreate ingress/client; no process-local result cache can provide replay.
        async with environment() as (client, _):
            assert await invoke(client, "execute_operation", ref) == first

    asyncio.run(run())
    import sqlite3

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT id,balance_cents FROM accounts ORDER BY id"
        ).fetchall() == [
            ("acct-alice", 980000),
            ("acct-bob", 1020000),
        ]


@pytest.mark.parametrize("amount,decision", [(100, "ALLOW"), (100001, "DENY")])
def test_policy_parity(environment, amount, decision):
    async def run():
        async with environment() as (client, _):
            body = await invoke(client, "request_operation", submission(amount), 201)
            assert body["decision"] == decision
            if decision == "DENY":
                await invoke(client, "execute_operation", {"operation_id": body["id"]}, 403)

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        {"principal_id": "secret-sentinel"},
        {"role": "APPROVER"},
        {"approver_id": "secret-sentinel"},
        {"policy_override": "ALLOW"},
        {"idempotency_key": "../bad"},
        {"tool_name": "sql"},
        {"arguments": {"account_id": "acct-alice"}},
        {
            "arguments": {
                "source_account_id": "acct-alice",
                "destination_account_id": "acct-bob",
                "amount_cents": True,
                "currency": "USD",
            }
        },
        {
            "arguments": {
                "source_account_id": "acct-alice",
                "destination_account_id": "acct-bob",
                "amount_cents": "20000",
                "currency": "USD",
            }
        },
    ],
)
def test_invalid_submission_is_sanitized(environment, bad, caplog):
    async def run():
        async with environment() as (client, _):
            result = await invoke(client, "request_operation", {**submission(), **bad}, 422)
            assert result == {"http_status": 422, "error": "INVALID_INPUT"}

    asyncio.run(run())
    assert "secret-sentinel" not in caplog.text


@pytest.mark.parametrize(
    "bad",
    [
        {"operation_id": "../../audit"},
        {"operation_id": str(uuid4()), "amount_cents": 1},
        {"operation_id": str(uuid4()), "arguments": {}},
    ],
)
def test_execution_cannot_replace_intent(environment, bad):
    async def run():
        async with environment() as (client, _):
            await invoke(client, "execute_operation", bad, 422)

    asyncio.run(run())


def test_foreign_operation_is_concealed_and_inspection_is_read_only(environment, database):
    import sqlite3

    async def run():
        async with environment() as (client, _):
            pending = await invoke(client, "request_operation", submission(), 201)
            ref = {"operation_id": pending["id"]}
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE operations SET principal_id='principal-other'")
                connection.execute("UPDATE approvals SET principal_id='principal-other'")
                before = list(connection.iterdump())
            await invoke(client, "get_operation", ref, 404)
            await invoke(client, "execute_operation", ref, 404)
            with sqlite3.connect(database) as connection:
                assert list(connection.iterdump()) == before

    asyncio.run(run())


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 401),
        ({"Authorization": "Bearer " + AGENT_TOKEN}, 401),
        ({"Authorization": "Bearer " + APPROVER_TOKEN}, 401),
        ({"Host": "evil.example"}, 403),
        ({"Host": "127.0.0.1:8002.evil"}, 403),
        ({"Origin": "https://evil.example"}, 403),
        ({"Origin": "null"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_transport_security_and_authentication(environment, headers, status):
    async def run():
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE
            ) as c:
                response = await c.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                assert response.status_code == status
                assert MCP_TOKEN not in response.text and AGENT_TOKEN not in response.text

    asyncio.run(run())


def test_streamed_request_limit_and_health(environment):
    async def chunks():
        for _ in range(5):
            yield b"x" * 4096

    async def run():
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE
            ) as c:
                assert (await c.get("/health")).status_code == 200
                response = await c.post(
                    "/mcp",
                    content=chunks(),
                    headers={
                        "Authorization": "Bearer " + MCP_TOKEN,
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 413

    asyncio.run(run())


def test_repeated_initialization_keeps_no_session_and_closes_upstream(environment, monkeypatch):
    original_gateway = mcp.build_mcp_gateway
    upstream_clients = []

    def gateway():
        upstream, adapter = original_gateway()
        upstream_clients.append(upstream)
        return upstream, adapter

    monkeypatch.setattr(mcp, "build_mcp_gateway", gateway)

    async def run():
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=BASE,
                headers={
                    "Authorization": "Bearer " + MCP_TOKEN,
                    "Accept": "application/json, text/event-stream",
                },
            ) as client:
                for request_id in range(8):
                    response = await client.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "session-regression", "version": "1"},
                            },
                        },
                    )
                    assert response.status_code == 200
                    assert "result" in response.json()
                    assert "mcp-session-id" not in response.headers
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 9,
                        "method": "tools/list",
                    },
                    headers={"MCP-Protocol-Version": "2025-11-25"},
                )
                assert response.status_code == 200
                assert len(response.json()["result"]["tools"]) == 3
                assert "mcp-session-id" not in response.headers
        assert upstream_clients and all(client.is_closed for client in upstream_clients)

    asyncio.run(asyncio.wait_for(run(), timeout=5))


@pytest.mark.parametrize(
    "body",
    [
        b'{"jsonrpc":"secret-sentinel","id":1,"method":"tools/list"}',
        b'{"jsonrpc":"2.0","id":{},"method":"secret-sentinel"}',
        b'{"secret-sentinel":',
    ],
)
def test_malformed_protocol_never_echoes_raw_input(environment, body, caplog):
    async def run():
        app = mcp.create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=BASE,
            ) as client:
                response = await client.post(
                    "/mcp",
                    content=body,
                    headers={
                        "Authorization": "Bearer " + MCP_TOKEN,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                assert response.status_code == 400
                assert "secret-sentinel" not in response.text

    asyncio.run(run())
    assert "secret-sentinel" not in caplog.text


@pytest.mark.parametrize("failure", ["connect", "timeout", "html", "server", "rejected"])
def test_gateway_failures_are_sanitized(failure):
    async def respond(request):
        assert request.url.host == "api"
        assert request.headers["authorization"] == "Bearer " + AGENT_TOKEN
        if failure == "connect":
            raise httpx.ConnectError("secret-sentinel")
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-sentinel")
        if failure == "html":
            return httpx.Response(200, text="secret-sentinel")
        return httpx.Response(
            422 if failure == "rejected" else 500, json={"error": "secret-sentinel"}
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://api"
        ) as c:
            status, body = await LocalMcpApiGateway(c, AGENT_TOKEN).run_operation(str(uuid4()))
            assert status >= 400 and "secret-sentinel" not in json.dumps(body)

    asyncio.run(run())


@pytest.mark.parametrize("enabled,token", [("0", MCP_TOKEN), ("1", "weak"), ("1", AGENT_TOKEN)])
def test_fail_closed_configuration(monkeypatch, enabled, token):
    monkeypatch.setenv("AGENTGATE_MCP_ENABLED", enabled)
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", token)
    monkeypatch.setenv("AGENTGATE_AGENT_TOKEN", AGENT_TOKEN)
    with pytest.raises(ValueError):
        mcp.create_app()
