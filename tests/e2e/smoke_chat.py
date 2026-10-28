"""Fake-provider Docker chat workflow; real MCP, PostgreSQL and restart/replay evidence."""

import asyncio
import json
from pathlib import Path

import httpx
from smoke_lab import compose
from smoke_mcp import snapshot

from agentgate.infrastructure.gateways.sdk_agent_mcp_gateway import SdkAgentMcpGateway

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:8080"


def main():
    with httpx.Client(base_url=ORIGIN, timeout=40, trust_env=False) as client:
        assert client.get("/lab/chat/status").json()["available"], (
            "Use compose.chat-test.yaml explicitly"
        )
        csrf = client.get("/lab/session").json()["csrf"]
        headers = {"Origin": ORIGIN, "X-Lab-CSRF": csrf}

        def turn(**body):
            response = client.post("/lab/chat/turn", json=body, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result["error"] is None, result["error"]
            return result

        before = snapshot()
        allowed = turn(message="Transfer $1 from Alice to Bob.")
        allow_id = allowed["operations"][-1]["id"]
        assert snapshot() == before, "Proposal executed implicitly"
        done = turn(action="execute", operation_id=allow_id)
        assert done["operations"][-1]["state"] == "SUCCEEDED"
        approved = turn(message="Transfer $100.01 from Alice to Bob.")
        op = approved["operations"][-1]
        assert op["state"] == "PENDING_APPROVAL"
        blocked = turn(action="execute", operation_id=op["id"])
        assert blocked["events"][-1]["result"]["http_status"] == 409
        human = client.post(
            "/lab/operations/" + op["id"] + "/approval",
            json={"decision": "APPROVE"},
            headers=headers,
        )
        assert human.status_code == 200
        done = turn(action="execute", operation_id=op["id"])
        assert done["operations"][-1]["state"] == "SUCCEEDED"
        first = done["operations"][-1]
        assert first["effective_reason"] == "HUMAN_APPROVED"
        replay = turn(action="execute", operation_id=op["id"])
        assert replay["operations"][-1] == first
        denied = turn(message="Transfer $1,000.01 from Alice to Bob.")
        assert denied["operations"][-1]["state"] == "DENIED"
        after = snapshot()
        assert after == {
            "acct-alice": before["acct-alice"] - 10101,
            "acct-bob": before["acct-bob"] + 10101,
        }
        assert sum(after.values()) == sum(before.values())
        row = snapshot(op["id"])
        assert row["successes"] == 1 and row["approval_status"] == "CONSUMED"
        print(
            "PASS: chat ALLOW/DENY/REQUIRE_APPROVAL; independent human approval; "
            "explicit MCP execution and replay; PostgreSQL total conserved; one success"
        )
        # Existing containers retain their command/config on restart, including test overlay.
        compose("restart", "postgres")
        compose("up", "-d", "--wait", "postgres")
        compose("restart", "api")
        compose("up", "-d", "--wait", "api")
        compose("restart", "mcp", "lab-bff", "frontend")
        compose("up", "-d", "--wait", "mcp")
        token = (ROOT / ".lab-secrets/mcp_token").read_text().strip()

        async def replay_after_restart():
            gateway = SdkAgentMcpGateway(token, "http://127.0.0.1:8002/mcp")
            result = await gateway.call("execute_operation", {"operation_id": op["id"]})
            assert result["state"] == "SUCCEEDED" and result["result"] == first["result"]

        asyncio.run(replay_after_restart())
        assert snapshot() == after and snapshot(op["id"]) == row
        print(
            "PASS: API/MCP/BFF/frontend/PostgreSQL restart retained identical approved operation, "
            "result, balances and one success; official MCP replay has no additional effect"
        )
        evidence = {
            "mode": "fake LLM, real MCP/API/PostgreSQL",
            "operation_id": op["id"],
            "decision": first["decision"],
            "state": first["state"],
            "successes": row["successes"],
            "conserved_total": sum(after.values()),
            "restart_replay": True,
        }
        directory = ROOT / ".lab-artifacts"
        directory.mkdir(exist_ok=True)
        (directory / "chat-smoke.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence))


if __name__ == "__main__":
    main()
