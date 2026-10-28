"""Exercise the real loopback Compose lab, including container restart durability."""

import subprocess
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:8080"


def compose(*arguments: str) -> None:
    result = subprocess.run(
        ["docker", "compose", *arguments], cwd=ROOT, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError("Docker smoke lifecycle command failed; inspect compose status/logs")


def main() -> None:
    with httpx.Client(base_url=ORIGIN, timeout=8, trust_env=False) as client:

        def request(method, path, body=None, *, key=None, expected=200):
            headers = {"Origin": ORIGIN, "X-Lab-CSRF": csrf}
            if key:
                headers["Idempotency-Key"] = key
            response = client.request(method, "/lab" + path, headers=headers, json=body)
            assert response.status_code == expected, (path, response.status_code)
            return response.json()

        session = client.get("/lab/session")
        session.raise_for_status()
        csrf = session.json()["csrf"]
        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/style.css").status_code == 200
        with httpx.Client(trust_env=False) as api:
            assert api.get("http://127.0.0.1:8001/docs").status_code == 200
            schema = api.get("http://127.0.0.1:8001/openapi.json").json()
            assert "/operations/{id}/execute" in schema["paths"]

        before = {a["id"]: a["balance_cents"] for a in request("GET", "/accounts")}
        assert before["acct-alice"] >= 20100, "Demo account needs funds for smoke transfers"

        def submit(amount, key):
            return request(
                "POST",
                "/operations",
                {
                    "tool": "simulate_transfer",
                    "arguments": {
                        "source_account_id": "acct-alice",
                        "destination_account_id": "acct-bob",
                        "amount_cents": amount,
                        "currency": "USD",
                    },
                },
                key=key,
                expected=201,
            )

        allow = submit(100, "smoke-allow-" + uuid4().hex)
        assert allow["decision"] == "ALLOW"
        request("POST", "/operations/" + allow["id"] + "/execute")
        denied = submit(100001, "smoke-deny-" + uuid4().hex)
        assert denied["decision"] == "DENY"
        request("POST", "/operations/" + denied["id"] + "/execute", expected=403)
        key = "smoke-approval-" + uuid4().hex
        approved = submit(20000, key)
        assert approved["decision"] == "REQUIRE_APPROVAL"
        path = "/operations/" + approved["id"]
        request("POST", path + "/execute", expected=409)
        request("POST", path + "/approval", {"decision": "APPROVE"})
        first = request("POST", path + "/execute")
        assert first["state"] == "SUCCEEDED" and first["effective_reason"] == "HUMAN_APPROVED"
        assert request("POST", path + "/execute") == first
        rejected = submit(20000, "smoke-reject-" + uuid4().hex)
        request("POST", "/operations/" + rejected["id"] + "/approval", {"decision": "REJECT"})
        request("POST", "/operations/" + rejected["id"] + "/execute", expected=409)
        after = {a["id"]: a["balance_cents"] for a in request("GET", "/accounts")}
        assert after == {
            "acct-alice": before["acct-alice"] - 20100,
            "acct-bob": before["acct-bob"] + 20100,
        }
        print("PASS: ALLOW, DENY, pending, approve, reject, execute, replay and conserved balances")

        assert (
            client.post(
                "/lab/operations", json={}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.post("/lab/operations", json={}, headers={"Origin": ORIGIN}).status_code == 403
        )
        assert client.get("/lab/accounts", headers={"Host": "evil.example"}).status_code == 403
        print("PASS: loopback proxy rejects hostile Host/Origin and absent CSRF")

        compose("restart", "postgres")
        compose("up", "-d", "--wait", "postgres")
        compose("restart", "api")
        compose("up", "-d", "--wait")

        # Refresh the browser session after service restarts.
        session = client.get("/lab/session")
        session.raise_for_status()
        csrf = session.json()["csrf"]

        # Verify durable replay after restart.
        assert request("POST", path + "/execute") == first

        replay = request(
            "POST",
            "/operations",
            {
                "tool": "simulate_transfer",
                "arguments": {
                    "source_account_id": "acct-alice",
                    "destination_account_id": "acct-bob",
                    "amount_cents": 20000,
                    "currency": "USD",
                },
            },
            key=key,
        )
        assert replay["id"] == approved["id"] and replay["result"] == first["result"]
        assert {a["id"]: a["balance_cents"] for a in request("GET", "/accounts")} == after
        events, cursor = [], 0
        while True:
            page = request("GET", "/audit?after=" + str(cursor))
            events.extend(page["events"])
            if not page["events"]:
                break
            assert page["next_after"] > cursor
            cursor = page["next_after"]
        relevant = [e for e in events if e["operation_id"] == approved["id"]]
        assert sum(e["event_type"] == "OPERATION_EXECUTED" for e in relevant) == 1
        assert any(e["event_type"] == "APPROVAL_DECIDED" for e in relevant)
        print(
            "PASS: PostgreSQL + API restart preserves balances, approval, "
            "idempotency and one success audit"
        )
        print("Approved operation: " + approved["id"])
        print("Balances (cents): " + str(after))


if __name__ == "__main__":
    main()
