"""Task 6.1: HTTPX-backed in-process API flows over disposable SQLite."""

import sqlite3
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentgate.application.exceptions.commit_uncertain import CommitUncertain
from agentgate.dependencies import build_components, get_principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.gateways.local_tool_registry_gateway import LocalToolRegistryGateway
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.tools.get_balance_adapter import GetBalanceAdapter
from agentgate.infrastructure.tools.simulate_transfer_adapter import SimulateTransferAdapter
from agentgate.main import create_app
from tests.api.test_request_endpoint import headers, payload
from tests.api.test_strict_input import snapshot
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN


@pytest.fixture
def api(settings, clock):
    components = build_components(settings)
    components = replace(
        components,
        request_operation=RequestOperationHandler(
            lambda: SqliteUnitOfWork(settings.database),
            EvaluatePolicyHandler(),
            clock,
            UuidOperationIdGenerator(),
        ),
        approve_operation=ApproveOperationHandler(
            lambda: SqliteUnitOfWork(settings.database), clock
        ),
    )
    # Use the same fake wall/monotonic clock for all lifecycle boundaries.
    components = replace(
        components,
        execute_operation=ExecuteOperationHandler(
            lambda: SqliteUnitOfWork(settings.database),
            LocalToolRegistryGateway(GetBalanceAdapter(), SimulateTransferAdapter()),
            EvaluatePolicyHandler(),
            clock,
            SimpleNamespace(sleep=lambda seconds: None),
            components.credentials,
        ),
    )
    with TestClient(create_app(components)) as client:
        yield client


def submit(api, amount=1, key="flow"):
    response = api.post("/operations", headers=headers(key), json=payload(amount))
    assert response.status_code == 201, response.text
    assert response.json()["simulation"] is True
    return response.json()


def execute(api, operation):
    return api.post(f"/operations/{operation['id']}/execute", headers=headers())


def approve(api, operation, decision="APPROVE"):
    return api.post(
        f"/operations/{operation['id']}/approval",
        headers=headers(token=APPROVER_TOKEN),
        json={"decision": decision},
    )


def balances(database):
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT id, balance_cents FROM accounts ORDER BY id").fetchall()


@pytest.mark.parametrize("amount", [1, 10000, 10001, 100000])
def test_transfer_full_lifecycle_replay_restart_and_funds(api, settings, database, amount):
    operation = submit(api, amount)
    before = balances(database)
    if amount > 10000:
        assert operation["decision"] == "REQUIRE_APPROVAL"
        assert execute(api, operation).status_code == 409
        granted = approve(api, operation)
        assert granted.status_code == 200
        assert granted.json()["decision"] == "REQUIRE_APPROVAL"
        assert granted.json()["approval_state"] == "GRANTED"
        assert balances(database) == before
        assert approve(api, operation).status_code == 409
    result = execute(api, operation)
    assert result.status_code == 200, result.text
    envelope = result.json()
    assert envelope["state"] == "SUCCEEDED"
    assert envelope["simulation"] is True
    assert envelope["result"] == payload(amount)["arguments"]
    assert envelope["effective_reason"] == ("HUMAN_APPROVED" if amount > 10000 else "PERMITTED")
    after = balances(database)
    assert [row[1] for row in after] == [1000000 - amount, 1000000 + amount]
    assert sum(row[1] for row in before) == sum(row[1] for row in after)
    committed = snapshot(database)
    assert execute(api, operation).json() == envelope
    assert snapshot(database) == committed
    with TestClient(create_app(build_components(settings))) as reopened:
        assert execute(reopened, operation).json() == envelope
        read = reopened.get(f"/operations/{operation['id']}", headers=headers())
        assert read.status_code == 200
        assert read.json()["result"] == envelope["result"]
        assert read.json()["simulation"] is True
        replay = reopened.post("/operations", headers=headers("flow"), json=payload(amount))
        assert replay.status_code == 200
        assert replay.json()["result"] == envelope["result"]
    assert snapshot(database) == committed


def test_balance_execution_and_inspection(api, database):
    operation = api.post(
        "/operations",
        headers=headers(),
        json={"tool": "get_balance", "arguments": {"account_id": "acct-alice"}},
    ).json()
    before = balances(database)
    response = execute(api, operation)
    assert response.status_code == 200
    assert response.json()["result"] == {
        "account_id": "acct-alice",
        "balance_cents": 1000000,
        "currency": "USD",
    }
    assert balances(database) == before


@pytest.mark.parametrize("scenario", ["deny", "reject", "pending", "expired", "granted_expired"])
def test_nonexecutable_lifecycles_never_dispatch(api, database, clock, scenario):
    operation = submit(api, 100001 if scenario == "deny" else 10001)
    before = balances(database)
    if scenario == "reject":
        assert approve(api, operation, "REJECT").status_code == 200
    if scenario == "granted_expired":
        assert approve(api, operation).status_code == 200
    if "expired" in scenario:
        clock.value += timedelta(seconds=300)
        assert approve(api, operation).status_code == 409
    response = execute(api, operation)
    assert response.status_code == (403 if scenario == "deny" else 409)
    assert response.json() == {"error": "FORBIDDEN" if scenario == "deny" else "INVALID_LIFECYCLE"}
    assert balances(database) == before
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'OPERATION_DISPATCHED'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "body",
    [{}, {"arguments": payload()["arguments"]}, {"decision": "APPROVE"}, {"tool": "get_balance"}],
)
def test_execute_accepts_only_path_id(api, database, body):
    operation = submit(api)
    before = snapshot(database)
    response = api.post(f"/operations/{operation['id']}/execute", headers=headers(), json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "INVALID_INPUT"}
    assert snapshot(database) == before


@pytest.mark.parametrize("decision", ["ALLOW", "approve", True, None])
def test_approval_input_is_closed(api, database, decision):
    operation = submit(api, 10001)
    before = snapshot(database)
    assert approve(api, operation, decision).status_code == 422
    assert snapshot(database) == before


def test_identity_ownership_missing_and_invalid_ids(api, database, principal):
    operation = submit(api, 10001)
    path = f"/operations/{operation['id']}"
    before = snapshot(database)
    for suffix, method in [("", api.get), ("/approval", api.post), ("/execute", api.post)]:
        for auth in [{}, {"Authorization": "Bearer invalid"}]:
            response = method(
                path + suffix,
                headers=auth,
                **({"json": {"decision": "APPROVE"}} if suffix == "/approval" else {}),
            )
            assert response.status_code == 401
    assert (
        api.post(path + "/approval", headers=headers(), json={"decision": "APPROVE"}).status_code
        == 403
    )
    assert api.post(path + "/execute", headers=headers(token=APPROVER_TOKEN)).status_code == 403
    assert api.get(path, headers=headers(token=APPROVER_TOKEN)).status_code == 200
    other = replace(principal, id=PrincipalId("principal-other"))
    api.app.dependency_overrides[get_principal] = lambda: other
    assert api.get(path, headers=headers()).status_code == 404
    assert api.post(path + "/execute", headers=headers()).status_code == 404
    api.app.dependency_overrides.clear()
    for id in [str(uuid4()), "invalid"]:
        expected = 422 if id == "invalid" else 404
        assert api.get(f"/operations/{id}", headers=headers()).status_code == expected
        assert api.post(f"/operations/{id}/execute", headers=headers()).status_code == expected
        assert (
            api.post(
                f"/operations/{id}/approval",
                headers=headers(token=APPROVER_TOKEN),
                json={"decision": "APPROVE"},
            ).status_code
            == expected
        )
    assert snapshot(database) == before


def test_queries_are_read_only_even_after_expiry_and_audit_is_paginated(api, database, clock):
    operation = submit(api, 10001)
    clock.value += timedelta(seconds=300)
    before = snapshot(database)
    for _ in range(2):
        for token in [AGENT_TOKEN, APPROVER_TOKEN]:
            read = api.get(f"/operations/{operation['id']}", headers=headers(token=token))
            assert read.status_code == 200
            assert read.json()["approval"]["state"] == "PENDING"
        assert api.get("/audit", headers=headers()).status_code == 403
        assert api.get("/audit").status_code == 401
        audit = api.get("/audit?limit=1", headers=headers(token=APPROVER_TOKEN))
        assert audit.status_code == 200
        event = audit.json()["events"][0]
        assert event["operation_id"] == operation["id"]
        next_page = api.get(
            f"/audit?after={event['id']}&limit=1", headers=headers(token=APPROVER_TOKEN)
        )
        assert next_page.json()["events"] == []
        assert api.get("/audit?limit=101", headers=headers(token=APPROVER_TOKEN)).status_code == 422
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "field,value", [("AGENTGATE_AGENT_TOKEN", None), ("AGENTGATE_AGENT_TOKEN", "short")]
)
def test_application_startup_rejects_invalid_credentials(monkeypatch, field, value):
    monkeypatch.setenv("AGENTGATE_AGENT_TOKEN", AGENT_TOKEN)
    monkeypatch.setenv("AGENTGATE_APPROVER_TOKEN", APPROVER_TOKEN)
    if value is None:
        monkeypatch.delenv(field)
    else:
        monkeypatch.setenv(field, value)
    with pytest.raises(ValueError):
        create_app()


@pytest.mark.parametrize("outcome", ["FAILED", "TIMED_OUT"])
def test_terminal_http_result_is_durable_and_replayed(api, settings, database, clock, outcome):
    operation = submit(api)
    calls = []

    def dispatch(tool, arguments, accounts):
        calls.append(tool)
        if outcome == "FAILED":
            raise RuntimeError("private-tool-error")
        clock.elapsed += 2.0
        return arguments

    components = api.app.state.components
    executor = ExecuteOperationHandler(
        lambda: SqliteUnitOfWork(database),
        SimpleNamespace(dispatch=dispatch),
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=lambda seconds: None),
        components.credentials,
    )
    api.app.state.components = replace(components, execute_operation=executor)
    before = balances(database)
    first = execute(api, operation)
    assert first.status_code == 200, first.text
    assert first.json()["state"] == outcome
    assert first.json()["simulation"] is True
    assert first.json()["result"] is None
    committed = snapshot(database)
    assert execute(api, operation).json() == first.json()
    with TestClient(create_app(build_components(settings))) as reopened:
        assert execute(reopened, operation).json() == first.json()
        assert (
            reopened.get(f"/operations/{operation['id']}", headers=headers()).json()["state"]
            == outcome
        )
    assert len(calls) == 1
    assert balances(database) == before
    assert snapshot(database) == committed
    assert "private-tool-error" not in first.text


def test_storage_failure_is_sanitized_and_rolls_back(api, database):
    operation = submit(api)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TRIGGER reject_audit BEFORE INSERT ON audit_events
                              BEGIN SELECT RAISE(ABORT, 'private-storage-error'); END""")
    before = snapshot(database)
    response = execute(api, operation)
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    assert snapshot(database) == before


def test_uncertain_commit_returns_503_then_durable_execution(api, database, clock):
    operation = submit(api)

    class UncertainWork(SqliteUnitOfWork):
        def commit(self):
            # Rollback on exit leaves READY; this call cannot assume or redispatch.
            raise CommitUncertain

    components = api.app.state.components
    executor = ExecuteOperationHandler(
        lambda: UncertainWork(database),
        LocalToolRegistryGateway(GetBalanceAdapter(), SimulateTransferAdapter()),
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=lambda seconds: None),
        components.credentials,
        recovery_unit_of_work=lambda: SqliteUnitOfWork(database),
    )
    api.app.state.components = replace(components, execute_operation=executor)
    before = balances(database)
    response = execute(api, operation)
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    assert balances(database) == before
    api.app.state.components = components
    assert execute(api, operation).status_code == 200
    assert [row[1] for row in balances(database)] == [999999, 1000001]


@pytest.mark.parametrize("suffix", ["approval", "execute"])
def test_new_command_routes_share_body_limit(api, database, suffix):
    operation = submit(api, 10001)
    before = snapshot(database)
    response = api.post(
        f"/operations/{operation['id']}/{suffix}",
        headers=headers(token=APPROVER_TOKEN if suffix == "approval" else AGENT_TOKEN),
        content=b"x" * 16385,
    )
    assert response.status_code == 413
    assert response.json() == {"error": "BODY_TOO_LARGE"}
    assert snapshot(database) == before
