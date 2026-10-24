import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from agentgate.dependencies import build_components, get_principal
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.expire_approval.command import ExpireApprovalCommand
from agentgate.features.expire_approval.handler import ExpireApprovalHandler
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.main import create_app
from tests.api.test_request_endpoint import headers, payload
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture
from tests.infrastructure.test_transactional_persistence import persist, snapshot

operation = operation_fixture


@pytest.fixture
def client(settings):
    with TestClient(create_app(build_components(settings))) as instance:
        yield instance


def approver_headers():
    return {"Authorization": f"Bearer {APPROVER_TOKEN}"}


def test_existing_audit_query_exposes_expiry_without_mutation(client, database, operation, clock):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    clock.value = operation.created_at + timedelta(seconds=300)
    ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock).handle(
        ExpireApprovalCommand(operation.id)
    )
    before = snapshot(database)
    for _ in range(2):
        response = client.get("/audit", headers=approver_headers())
        assert response.status_code == 200
        event = response.json()["events"][-1]
        assert event["event_type"] == "APPROVAL_EXPIRED"
        assert event["decision"] == "EXPIRED"
        assert event["reason"] == "APPROVAL_EXPIRED"
        assert event["fingerprint"] == operation.request.fingerprint.value
        assert event["approver_id"] is None
    assert snapshot(database) == before


@pytest.mark.parametrize("token,status", [(None, 401), ("invalid", 401), (AGENT_TOKEN, 403)])
def test_audit_authentication_and_role(client, database, token, status):
    before = snapshot(database)
    authorization = {} if token is None else {"Authorization": f"Bearer {token}"}
    response = client.get("/audit", headers=authorization)
    assert response.status_code == status
    assert snapshot(database) == before


def test_audit_handler_rechecks_role_when_transport_identity_is_overridden(client, principal):
    client.app.dependency_overrides[get_principal] = lambda: principal
    response = client.get("/audit", headers=approver_headers())
    assert response.status_code == 403
    assert response.json() == {"error": "FORBIDDEN"}


def test_default_and_keyset_pages_are_bounded_and_sanitized(client, database, audit_history):
    before = snapshot(database)
    response = client.get("/audit", headers=approver_headers())
    assert response.status_code == 200
    first = response.json()
    assert first["simulation"] is True
    assert len(first["events"]) == 50
    assert [event["id"] for event in first["events"]] == list(range(1, 51))
    assert first["next_after"] == 50
    assert set(first["events"][0]) == {
        "id",
        "operation_id",
        "principal_id",
        "tool",
        "decision",
        "reason",
        "policy_version",
        "occurred_at",
        "event_type",
        "approver_id",
        "fingerprint",
        "attempt",
    }
    second = client.get("/audit?after=50&limit=100", headers=approver_headers()).json()
    assert [event["id"] for event in second["events"]] == list(range(51, 106))
    assert second["next_after"] == 105
    last = client.get("/audit?after=105&limit=1", headers=approver_headers()).json()
    assert last["events"] == []
    assert last["next_after"] == 105
    assert snapshot(database) == before
    for token in (AGENT_TOKEN, APPROVER_TOKEN):
        assert token not in response.text


@pytest.mark.parametrize("limit", [1, 100])
def test_valid_page_size_boundaries(client, audit_history, limit):
    response = client.get("/audit", params={"limit": limit}, headers=approver_headers())
    assert response.status_code == 200
    assert len(response.json()["events"]) == limit


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"limit": "true"},
        {"limit": "1.5"},
        {"after": -1},
        {"after": 2**63},
        {"after": "false"},
        {"after": "1.5"},
        {"after": "0; DROP TABLE accounts"},
    ],
)
def test_invalid_pagination_is_sanitized_without_writes(client, database, params):
    before = snapshot(database)
    response = client.get("/audit", params=params, headers=approver_headers())
    assert response.status_code == 422
    assert response.json() == {"error": "INVALID_INPUT"}
    assert snapshot(database) == before


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_audit_exposes_no_mutation_route(client, database, method):
    before = snapshot(database)
    assert client.request(method, "/audit", headers=approver_headers()).status_code == 405
    assert snapshot(database) == before


def test_audit_failure_rolls_back_request_and_approval_without_visible_event(client, database):
    before = snapshot(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events
               BEGIN SELECT RAISE(ABORT, 'SECRET_AUDIT_SENTINEL'); END"""
        )
    response = client.post("/operations", headers=headers(), json=payload(10001))
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    assert client.get("/audit", headers=approver_headers()).json()["events"] == []
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER fail_audit")
    assert snapshot(database) == before


def test_corrupt_audit_row_does_not_expose_raw_storage(client, database, audit_history, caplog):
    sentinel = "SECRET_AUDIT_SENTINEL\nforged-record"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE audit_events SET reason=? WHERE id=1", (sentinel,))
    response = client.get("/audit", headers=approver_headers())
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    assert sentinel not in response.text + caplog.text


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_existing_audit_endpoint_reads_human_decision_without_writes(
    client, database, operation, principal, clock, decision
):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    human = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
    ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock).handle(
        ApproveOperationCommand(human, operation.id, decision)
    )
    before = snapshot(database)
    for _ in range(2):
        response = client.get("/audit", headers=approver_headers())
        assert response.status_code == 200
        events = response.json()["events"]
        assert len(events) == 2
        assert events[0]["decision"] == "REQUIRE_APPROVAL"
        assert events[1]["event_type"] == "APPROVAL_DECIDED"
        assert events[1]["decision"] == decision.value
        assert events[1]["approver_id"] == human.id.value
        assert events[1]["principal_id"] == operation.principal_id.value
        assert events[1]["fingerprint"] == operation.request.fingerprint.value
        assert events[1]["policy_version"] == operation.policy.version.value
        assert events[1]["tool"] == operation.request.tool.value
    assert snapshot(database) == before
