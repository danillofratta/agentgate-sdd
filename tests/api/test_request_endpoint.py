import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentgate.dependencies import build_components
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.system_clock import SystemClock
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.main import create_app
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN


def payload(amount=1):
    return {
        "tool": "simulate_transfer",
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
    }


def headers(key="one", token=AGENT_TOKEN):
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


@pytest.fixture
def client(settings):
    with TestClient(create_app(build_components(settings))) as instance:
        yield instance


@pytest.mark.parametrize(
    "amount,decision,state",
    [
        (1, "ALLOW", "READY"),
        (10000, "ALLOW", "READY"),
        (10001, "REQUIRE_APPROVAL", "PENDING_APPROVAL"),
        (100000, "REQUIRE_APPROVAL", "PENDING_APPROVAL"),
        (100001, "DENY", "DENIED"),
    ],
)
def test_endpoint_decisions_and_no_transfer(client, database, amount, decision, state):
    response = client.post("/operations", headers=headers(), json=payload(amount))
    assert response.status_code == 201, response.text
    assert response.json()["decision"] == decision
    assert response.json()["state"] == state
    assert response.json()["simulation"] is True
    assert response.json()["result"] is None
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT SUM(balance_cents) FROM accounts").fetchone()[0] == 2000000
        )
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
        approvals = connection.execute("SELECT * FROM approvals").fetchall()
        assert len(approvals) == (decision == "REQUIRE_APPROVAL")
        if approvals:
            from datetime import datetime

            assert (
                datetime.fromisoformat(approvals[0][5]) - datetime.fromisoformat(approvals[0][4])
            ).total_seconds() == 300


def test_endpoint_idempotency_json_order_and_conflict(client, database):
    first = client.post("/operations", headers=headers(), json=payload(10001))
    reordered = {
        "arguments": dict(reversed(list(payload(10001)["arguments"].items()))),
        "tool": "simulate_transfer",
    }
    replay = client.post("/operations", headers=headers(), json=reordered)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert client.post("/operations", headers=headers(), json=payload(2)).status_code == 409
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


def test_request_replay_survives_app_recreation(settings):
    with TestClient(create_app(build_components(settings))) as first:
        original = first.post("/operations", headers=headers(), json=payload())
    with TestClient(create_app(build_components(settings))) as second:
        replay = second.post("/operations", headers=headers(), json=payload())
    assert replay.status_code == 200
    assert replay.json() == original.json()


@pytest.mark.parametrize("token,status", [(None, 401), ("invalid", 401), (APPROVER_TOKEN, 403)])
def test_authentication_and_role(client, token, status):
    request_headers = {"Idempotency-Key": "one"} if token is None else headers(token=token)
    assert client.post("/operations", headers=request_headers, json=payload()).status_code == status


@pytest.mark.parametrize(
    "body",
    [
        {"tool": "../../shell", "arguments": {}},
        {"tool": "simulate_transfer", "arguments": {}, "role": "APPROVER"},
        {"tool": "get_balance", "arguments": {"account_id": "acct-a' OR 1=1"}},
        {"tool": "get_balance", "arguments": {"account_id": "../etc/passwd"}},
        {"tool": "get_balance", "arguments": {"account_id": "acct-alice", "policy": "ALLOW"}},
        {"tool": "get_balance", "arguments": {"account_id": "acct-alice\n"}},
        {
            "tool": "simulate_transfer",
            "arguments": {
                "source_account_id": "acct-alice",
                "destination_account_id": "acct-alice",
                "amount_cents": 1,
                "currency": "USD",
            },
        },
        {},
        [],
        None,
    ],
)
def test_malicious_bodies_rejected_without_persistence(client, database, body):
    assert client.post("/operations", headers=headers(), json=body).status_code == 422
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("amount", [True, False, 0, -1, 1.5, "100", 2**63])
def test_amount_coercion_is_forbidden(client, amount):
    assert client.post("/operations", headers=headers(), json=payload(amount)).status_code == 422


@pytest.mark.parametrize("key", ["", "a" * 65, "bad/key"])
def test_invalid_keys(client, key):
    assert client.post("/operations", headers=headers(key=key), json=payload()).status_code == 422


def test_currency_and_missing_key_and_malformed_json(client):
    body = payload()
    body["arguments"]["currency"] = "EUR"
    assert client.post("/operations", headers=headers(), json=body).status_code == 422
    assert (
        client.post(
            "/operations", headers={"Authorization": f"Bearer {AGENT_TOKEN}"}, json=payload()
        ).status_code
        == 422
    )
    assert client.post("/operations", headers=headers(), content=b'{"bad":').status_code == 422


def test_streamed_body_is_bounded_without_content_length(client, database):

    def chunks():
        for _ in range(5):
            yield (b"x" * 4096)

    response = client.post("/operations", headers=headers(), content=chunks())
    assert response.status_code == 413
    assert response.json() == {"error": "BODY_TOO_LARGE"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_audit_failure_rolls_back_sql_transaction(client, database):
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events
               BEGIN SELECT RAISE(ABORT, 'secret-database-sentinel'); END"""
        )
    response = client.post("/operations", headers=headers(), json=payload(10001))
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    with sqlite3.connect(database) as connection:
        for table in ("operations", "approvals", "audit_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert (
            connection.execute("SELECT SUM(balance_cents) FROM accounts").fetchone()[0] == 2000000
        )


def test_policy_exception_secret_is_absent_from_all_output(settings, caplog):
    secret = "UNTRUSTED_SECRET_SENTINEL\nforged-record"

    def uncertain(snapshot):
        raise RuntimeError(secret)

    components = build_components(settings)
    use_case = RequestOperationHandler(
        lambda: SqliteUnitOfWork(settings.database),
        SimpleNamespace(evaluate=uncertain),
        SystemClock(),
        UuidOperationIdGenerator(),
    )
    with TestClient(create_app(replace(components, request_operation=use_case))) as client:
        response = client.post("/operations", headers=headers(), json=payload())
        assert response.json()["reason"] == "POLICY_UNCERTAIN"
        rejected = client.post(
            "/operations", headers=headers("other"), json={"role": secret, "token": AGENT_TOKEN}
        )
        assert rejected.status_code == 422
    with sqlite3.connect(settings.database) as connection:
        dump = " ".join(connection.iterdump())
    for sentinel in (secret, AGENT_TOKEN, APPROVER_TOKEN, "Traceback"):
        assert sentinel not in response.text + rejected.text + caplog.text + dump


def test_no_unrelated_slice_endpoints(client):
    paths = client.app.openapi()["paths"]
    assert set(paths) == {"/operations"}
    assert set(paths["/operations"]) == {"post"}
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404


def test_request_balance_checks_ownership(client):
    allowed = client.post(
        "/operations",
        headers=headers(),
        json={"tool": "get_balance", "arguments": {"account_id": "acct-alice"}},
    )
    denied = client.post(
        "/operations",
        headers=headers("two"),
        json={"tool": "get_balance", "arguments": {"account_id": "acct-bob"}},
    )
    assert allowed.json()["decision"] == "ALLOW"
    assert denied.json()["reason"] == "SOURCE_NOT_ALLOWED"


def test_oversized_single_chunk(client):
    response = client.post("/operations", headers=headers(), content=b"x" * 16385)
    assert response.status_code == 413


def test_request_payload_is_not_logged(client, caplog):
    malicious = json.dumps({"prompt": "LOG_INJECTION_SENTINEL\nforged", "token": AGENT_TOKEN})
    response = client.post("/operations", headers=headers(), content=malicious)
    assert response.status_code == 422
    assert "LOG_INJECTION_SENTINEL" not in response.text + caplog.text
    assert AGENT_TOKEN not in response.text + caplog.text
