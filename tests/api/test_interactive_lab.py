import secrets
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.dependencies import build_components
from agentgate.features.list_accounts.query import ListAccountsQuery
from agentgate.infrastructure.gateways.local_demo_api_gateway import LocalDemoApiGateway
from agentgate.infrastructure.repositories.sqlite_account_read_repository import (
    SqliteAccountReadRepository,
)
from agentgate.lab import create_app as create_lab
from agentgate.main import create_app
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN


@pytest.fixture
def local_api(settings, monkeypatch, clock):
    monkeypatch.setattr("agentgate.dependencies.SystemClock", lambda: clock)
    with TestClient(
        create_app(build_components(settings), local=True), base_url="http://127.0.0.1:8000"
    ) as api:
        yield api


@pytest.fixture
def lab(monkeypatch, local_api):
    monkeypatch.setenv("AGENTGATE_LOCAL_DEVELOPMENT", "1")
    real_client = httpx.Client

    def upstream(request):
        assert request.url.host == "api"
        assert request.headers["Authorization"] in {
            "Bearer " + AGENT_TOKEN,
            "Bearer " + APPROVER_TOKEN,
        }
        return httpx.Response(
            **response_values(
                local_api.request(
                    request.method,
                    request.url.path
                    + ("?" + request.url.query.decode() if request.url.query else ""),
                    content=request.content,
                    headers={key: value for key, value in request.headers.items() if key != "host"},
                )
            )
        )

    def response_values(response):
        return {"status_code": response.status_code, "json": response.json()}

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(upstream)
        return real_client(*args, **kwargs)

    # Only the real gateway's internal HTTP client uses this fake local transport.
    with TestClient(
        create_lab(LocalDemoApiGateway(AGENT_TOKEN, APPROVER_TOKEN)),
        base_url="http://127.0.0.1:8080",
    ) as client:
        monkeypatch.setattr(httpx, "Client", factory)
        yield client


def headers(lab):
    session = lab.get("/lab/session")
    assert session.status_code == 200
    return {
        "Origin": "http://127.0.0.1:8080",
        "X-Lab-CSRF": session.json()["csrf"],
        "Idempotency-Key": "lab-test",
    }


def payload(amount=20000):
    return {
        "tool": "simulate_transfer",
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
    }


def test_lab_full_workflow_and_secret_isolation(lab):
    h = headers(lab)
    assets = "".join(lab.get(path).text for path in ["/", "/app.js", "/style.css"])
    assert "Your workspace, at a glance" in assets
    assert assets.count('id="operation-workspace"') == 1
    assert '<details id="inspector" class="panel inspector">' in assets
    assert lab.get("/").headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in lab.get("/").headers["content-security-policy"]
    before = lab.get("/lab/accounts").json()
    operation = lab.post("/lab/operations", json=payload(), headers=h)
    assert operation.status_code == 201
    assert operation.json()["decision"] == "REQUIRE_APPROVAL"
    path = "/lab/operations/" + operation.json()["id"]
    assert lab.post(path + "/execute", headers=h).status_code == 409
    assert lab.post(path + "/approval", json={"decision": "APPROVE"}, headers=h).status_code == 200
    first = lab.post(path + "/execute", headers=h)
    assert first.status_code == 200 and first.json()["state"] == "SUCCEEDED"
    assert lab.post(path + "/execute", headers=h).json() == first.json()
    assert lab.get("/lab/accounts").json()[0]["balance_cents"] == before[0]["balance_cents"] - 20000
    audit = lab.get("/lab/audit").json()
    assert sum(e["event_type"] == "OPERATION_EXECUTED" for e in audit["events"]) == 1
    raw = assets + operation.text + first.text + str(audit)
    assert AGENT_TOKEN not in raw and APPROVER_TOKEN not in raw


@pytest.mark.parametrize(
    "bad",
    [
        {"Origin": "https://evil.example"},
        {"Host": "evil.example:8080"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"X-Lab-CSRF": ""},
        {"X-Lab-CSRF": secrets.token_hex(32)},
        {"Authorization": "Bearer untrusted"},
    ],
)
def test_proxy_rejects_untrusted_context(lab, bad):
    h = {**headers(lab), **bad}
    assert lab.post("/lab/operations", json=payload(), headers=h).status_code == 403
    assert lab.get("/lab/audit").json()["events"] == []


def test_csrf_is_session_bound(lab):
    h = headers(lab)
    lab.get("/lab/session")
    assert lab.post("/lab/operations", json=payload(), headers=h).status_code == 403


def test_original_idempotency_survives_repeated_csrf_renewal_and_reconciliation(lab):
    original = headers(lab)
    intent = payload(10001)
    before = lab.get("/lab/accounts").json()
    # The server committed this response, but the browser may not have received it.
    created = lab.post("/lab/operations", json=intent, headers=original).json()
    current_headers = original
    for _ in range(3):
        renewed = headers(lab)
        rejected = lab.post("/lab/operations", json=intent, headers=current_headers)
        assert rejected.status_code == 403
        assert rejected.json() == {"error": "LAB_FORBIDDEN"}
        reconciled = lab.post("/lab/operations", json=intent, headers=renewed)
        assert reconciled.status_code == 200
        assert reconciled.json()["id"] == created["id"]
        current_headers = renewed
    assert lab.get("/lab/accounts").json() == before
    events = lab.get("/lab/audit").json()["events"]
    assert len(events) == 1 and events[0]["event_type"] == "OPERATION_REQUESTED"
    path = "/lab/operations/" + created["id"]
    lab.post(path + "/approval", json={"decision": "APPROVE"}, headers=current_headers)
    assert lab.get("/lab/accounts").json() == before
    first = lab.post(path + "/execute", headers=current_headers).json()
    after = lab.get("/lab/accounts").json()
    assert first["state"] == "SUCCEEDED"
    renewed = headers(lab)
    assert lab.get(path).json()["state"] == "SUCCEEDED"
    assert lab.post(path + "/execute", headers=renewed).json() == first
    assert lab.get("/lab/accounts").json() == after
    assert after[0]["balance_cents"] == before[0]["balance_cents"] - 10001
    assert after[1]["balance_cents"] == before[1]["balance_cents"] + 10001
    events = lab.get("/lab/audit").json()["events"]
    assert sum(e["event_type"] == "OPERATION_EXECUTED" for e in events) == 1


def test_renewed_session_preserves_approved_operation_without_execution(lab):
    original_headers = headers(lab)
    before = lab.get("/lab/accounts").json()
    submitted = lab.post("/lab/operations", json=payload(10001), headers=original_headers).json()
    path = "/lab/operations/" + submitted["id"]
    assert lab.get(path).json()["approval"]["state"] == "PENDING"
    assert lab.get("/lab/accounts").json() == before
    renewed = headers(lab)
    assert (
        lab.post(path + "/approval", json={"decision": "APPROVE"}, headers=original_headers)
    ).status_code == 403
    assert lab.get(path).json()["state"] == "PENDING_APPROVAL"
    lab.post(path + "/approval", json={"decision": "APPROVE"}, headers=renewed).raise_for_status()
    restored = lab.get(path).json()
    assert restored["state"] == "READY"
    assert restored["approval"]["state"] == "GRANTED"
    assert restored["decision"] == "REQUIRE_APPROVAL"
    assert lab.get("/lab/accounts").json() == before
    first = lab.post(path + "/execute", headers=renewed).json()
    after = lab.get("/lab/accounts").json()
    assert first["state"] == "SUCCEEDED"
    assert lab.post(path + "/execute", headers=renewed).json() == first
    assert lab.get("/lab/accounts").json() == after
    assert after[0]["balance_cents"] == before[0]["balance_cents"] - 10001


@pytest.mark.parametrize("approve_first", [False, True])
def test_elapsed_approval_cannot_be_reused_and_reads_do_not_expire(lab, clock, approve_first):
    h = headers(lab)
    before = lab.get("/lab/accounts").json()
    submitted = lab.post("/lab/operations", json=payload(10001), headers=h).json()
    path = "/lab/operations/" + submitted["id"]
    if approve_first:
        lab.post(path + "/approval", json={"decision": "APPROVE"}, headers=h).raise_for_status()
    clock.value += timedelta(seconds=301)
    snapshot = lab.get(path).json()
    assert snapshot["state"] == ("READY" if approve_first else "PENDING_APPROVAL")
    assert snapshot["approval"]["state"] == ("GRANTED" if approve_first else "PENDING")
    assert lab.post(path + "/execute", headers=h).status_code == 409
    # The rejected command rolls back; expiry is not invented by inspection.
    assert lab.get(path).json()["state"] == snapshot["state"]
    assert lab.get("/lab/accounts").json() == before


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "approver"},
        {"url": "https://evil.example"},
        {"authorization": "secret"},
        {"policy": "ALLOW"},
    ],
)
def test_proxy_cannot_override_identity_destination_or_policy(lab, extra):
    h = headers(lab)
    response = lab.post("/lab/operations", json={**payload(), **extra}, headers=h)
    assert response.status_code == 422
    assert lab.get("/lab/audit").json()["events"] == []


def test_proxy_bounded_input_and_fixed_paths(lab):
    h = headers(lab)
    assert lab.post("/lab/operations", content="x" * 16385, headers=h).status_code == 413
    assert lab.get("/lab/operations/not-an-id").status_code == 422
    assert lab.get("/lab/proxy?url=https://evil.example").status_code == 404


def test_lab_deny_reject_and_balance_read(lab):
    h = headers(lab)
    denied = lab.post("/lab/operations", json=payload(100001), headers=h).json()
    assert denied["decision"] == "DENY"
    assert lab.post("/lab/operations/" + denied["id"] + "/execute", headers=h).status_code == 403
    h["Idempotency-Key"] = "rejected"
    pending = lab.post("/lab/operations", json=payload(), headers=h).json()
    path = "/lab/operations/" + pending["id"]
    assert lab.post(path + "/approval", json={"decision": "REJECT"}, headers=h).status_code == 200
    assert lab.post(path + "/execute", headers=h).status_code == 409
    h["Idempotency-Key"] = "balance"
    op = lab.post(
        "/lab/operations",
        json={"tool": "get_balance", "arguments": {"account_id": "acct-alice"}},
        headers=h,
    ).json()
    assert op["decision"] == "ALLOW"
    result = lab.post("/lab/operations/" + op["id"] + "/execute", headers=h).json()
    assert result["result"]["balance_cents"] == 1000000


def test_lab_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("AGENTGATE_LOCAL_DEVELOPMENT", raising=False)
    with pytest.raises(ValueError, match="AGENTGATE_LOCAL_DEVELOPMENT"):
        create_lab()


def test_local_swagger_and_host_protection(settings):
    components = build_components(settings)
    with TestClient(create_app(components, local=True), base_url="http://127.0.0.1:8000") as client:
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200 and "/operations" in schema.json()["paths"]
        assert AGENT_TOKEN not in schema.text and APPROVER_TOKEN not in schema.text
        assert client.get("/docs", headers={"Host": "evil.example"}).status_code == 400
    with TestClient(create_app(components, local=False)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_accounts_are_approver_only_read_only(local_api, settings, database, principal):
    assert local_api.get("/accounts").status_code == 401
    assert (
        local_api.get("/accounts", headers={"Authorization": "Bearer " + AGENT_TOKEN}).status_code
        == 403
    )
    human = {"Authorization": "Bearer " + APPROVER_TOKEN}
    assert local_api.get("/accounts", headers=human).json() == [
        {"id": "acct-alice", "balance_cents": 1000000, "currency": "USD"},
        {"id": "acct-bob", "balance_cents": 1000000, "currency": "USD"},
    ]
    assert local_api.get("/audit", headers=human).json()["events"] == []
    components = build_components(settings)
    with pytest.raises(Forbidden):
        components.list_accounts.handle(ListAccountsQuery(principal))
    from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
    from agentgate.domain.entities.account import Account
    from agentgate.domain.value_objects.account_id import AccountId

    with pytest.raises(StorageUnavailable):
        SqliteAccountReadRepository(database).save(Account(AccountId("acct-alice"), 0))
