"""Real Docker MCP verification. Creates synthetic operations and transfers 20,100 cents."""

import asyncio
import json
import subprocess
from uuid import UUID, uuid4

import httpx
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_client import ROOT, URL, connect
from smoke_lab import compose


def snapshot(operation_id=None):
    # Verification-only read access, never part of the MCP container or tool surface.
    query = "SELECT json_object_agg(id,balance_cents) FROM accounts"
    if operation_id is not None:
        value = str(UUID(operation_id))
        query = (
            "SELECT row_to_json(e) FROM (SELECT o.*, a.principal_id AS approval_owner, "
            "a.fingerprint AS approval_fingerprint, a.policy_version AS approval_policy, "
            "a.expires_at, a.status AS approval_status, a.approver_id, a.consumed_at, "
            "(SELECT count(*) FROM audit_events WHERE operation_id=o.id "
            "AND event_type='OPERATION_EXECUTED') AS successes "
            "FROM operations o JOIN approvals a ON a.operation_id=o.id "
            f"WHERE o.id='{value}') e"
        )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "agentgate",
            "-d",
            "agentgate",
            "-At",
            "-c",
            "BEGIN READ ONLY; " + query + "; COMMIT;",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "Read-only PostgreSQL verification failed"
    return json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))


async def call(client, name, arguments, status=200):
    result = await client.call_tool(name, arguments)
    assert result.is_error == (status >= 400), name
    body = result.structured_content
    assert body["http_status"] == status, (name, body["http_status"])
    return body


def submission(amount, key=None):
    return {
        "tool_name": "simulate_transfer",
        "idempotency_key": key or uuid4().hex,
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
    }


async def main():
    before = snapshot()
    assert before["acct-alice"] >= 20100, "Insufficient synthetic funds; no balances were reset"
    async with connect() as client:
        assert {tool.name for tool in (await client.list_tools()).tools} == {
            "request_operation",
            "get_operation",
            "execute_operation",
        }
        print("PASS: official SDK legacy initialization and discovery over Streamable HTTP")
        allowed = await call(client, "request_operation", submission(100), 201)
        assert allowed["decision"] == "ALLOW" and allowed["result"] is None
        await call(client, "execute_operation", {"operation_id": allowed["id"]})
        denied = await call(client, "request_operation", submission(100001), 201)
        assert denied["decision"] == "DENY"
        await call(client, "execute_operation", {"operation_id": denied["id"]}, 403)
        payload = submission(20000)
        # Competing requests must produce exactly one persisted operation.
        created = await asyncio.gather(
            *[client.call_tool("request_operation", payload) for _ in range(4)]
        )
        assert sorted(r.structured_content["http_status"] for r in created) == [200, 200, 200, 201]
        pending = created[0].structured_content
        assert len({r.structured_content["id"] for r in created}) == 1
        assert pending["decision"] == "REQUIRE_APPROVAL"
        ref = {"operation_id": pending["id"]}
        original = snapshot(pending["id"])
        await call(client, "execute_operation", ref, 409)
        await call(client, "approve_operation", {**ref, "decision": "APPROVE"}, 422)
        await call(client, "execute_operation", {**ref, "arguments": {"amount_cents": 1}}, 422)
        await call(
            client, "request_operation", {**payload, "principal_id": "principal-approver"}, 422
        )
        await call(client, "request_operation", {**payload, "role": "APPROVER"}, 422)
        await call(client, "request_operation", submission(True), 422)
        await call(
            client,
            "request_operation",
            {
                **payload,
                "arguments": {**payload["arguments"], "amount_cents": 20001},
            },
            409,
        )
        assert snapshot(pending["id"]) == original
        print(
            "PASS: ALLOW/DENY/pending; no approval tool, overrides, "
            "invalid amount or intent replacement"
        )

        # Independent existing human frontend workflow; no approver token is read by this client.
        origin = "http://127.0.0.1:8080"
        async with httpx.AsyncClient(base_url=origin, timeout=8, trust_env=False) as human:
            csrf = (await human.get("/lab/session")).json()["csrf"]
            grant = await human.post(
                "/lab/operations/" + pending["id"] + "/approval",
                json={"decision": "APPROVE"},
                headers={"Origin": origin, "X-Lab-CSRF": csrf},
            )
            assert grant.status_code == 200
        granted = snapshot(pending["id"])
        results = await asyncio.gather(*[call(client, "execute_operation", ref) for _ in range(4)])
        first = results[0]
        assert all(result == first for result in results)
        assert first["state"] == "SUCCEEDED" and first["effective_reason"] == "HUMAN_APPROVED"
        view = await call(client, "get_operation", ref)
        assert view["arguments"] == pending["arguments"]
        assert view["decision"] == "REQUIRE_APPROVAL" and view["approval"]["state"] == "CONSUMED"
        stored = snapshot(pending["id"])
        assert stored["successes"] == 1 and stored["approval_status"] == "CONSUMED"
        for field in (
            "principal_id",
            "key",
            "request_json",
            "fingerprint",
            "decision",
            "reason",
            "policy_version",
            "created_at",
            "approval_owner",
            "approval_fingerprint",
            "approval_policy",
            "expires_at",
        ):
            assert stored[field] == original[field], field
        assert stored["approver_id"] == granted["approver_id"] == "principal-approver"
        assert stored["approval_fingerprint"] == stored["fingerprint"]
        after = snapshot()
        assert after == {
            "acct-alice": before["acct-alice"] - 20100,
            "acct-bob": before["acct-bob"] + 20100,
        }
        print(
            "PASS: independent human approval; concurrent execution, "
            "one SQL success, immutable bindings"
        )

    async with connect(mode="auto") as client:
        assert (await client.list_tools()).tools
        assert await call(client, "execute_operation", ref) == first
    print("PASS: modern SDK protocol negotiation and durable replay")

    async with httpx.AsyncClient(timeout=8, trust_env=False) as http:
        for headers in (
            {},
            {"Authorization": "Bearer invalid"},
            {"Host": "evil.example"},
            {"Origin": "https://evil.example"},
        ):
            response = await http.post(
                URL,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "execute_operation", "arguments": ref},
                },
            )
            assert response.status_code in {401, 403}
    # Real SDK unauthorized initialization must fail too.
    rejected = False
    try:
        async with httpx2.AsyncClient(trust_env=False, timeout=5) as http:
            async with Client(
                streamable_http_client(URL, http_client=http), mode="legacy"
            ) as client:
                await client.call_tool("execute_operation", ref)
    except Exception:
        rejected = True
    assert rejected
    print("PASS: unauthenticated SDK client and hostile Host/Origin rejected")

    compose("restart", "api", "mcp")
    compose("up", "-d", "--wait")
    async with connect() as client:
        assert await call(client, "execute_operation", ref) == first
        replay = await call(client, "request_operation", payload)
        assert replay["id"] == pending["id"] and replay["result"] == first["result"]
        assert (await call(client, "get_operation", ref))["approval"] == view["approval"]
    assert snapshot() == after and snapshot(pending["id"]) == stored
    print(
        "PASS: API + MCP container restart; identical PostgreSQL state, "
        "balances, result, approval and audit"
    )
    print("Approved operation: " + pending["id"])
    print("Balances (cents): " + json.dumps(after))


if __name__ == "__main__":
    asyncio.run(main())
