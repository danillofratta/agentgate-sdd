from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from agentgate.application.exceptions.commit_uncertain import CommitUncertain
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.dependencies import build_components
from agentgate.domain.entities.account import Account
from agentgate.domain.enums.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.infrastructure.persistence.postgres_database import WRITE_LOCK, begin_read, connect
from agentgate.infrastructure.persistence.postgres_unit_of_work import PostgresUnitOfWork
from agentgate.infrastructure.repositories.postgres_audit_repository import PostgresAuditRepository
from agentgate.infrastructure.runtime.system_clock import SystemClock


def transfer(amount=100):
    return {
        "tool": "simulate_transfer",
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
    }


def submit(api, auth, amount=100, key=None):
    response = api.post(
        "/operations",
        json=transfer(amount),
        headers={**auth, "Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


def balances(database):
    with closing(connect(database)) as connection:
        begin_read(connection)
        return {
            row["id"]: row["balance_cents"] for row in connection.execute("SELECT * FROM accounts")
        }


def test_policy_approval_rejection_replay_and_idempotency(api, auth, human, pg_database):
    assert submit(api, auth, 100001)["decision"] == "DENY"
    pending = submit(api, auth, 20000, "approved")
    assert pending["decision"] == "REQUIRE_APPROVAL"
    path = "/operations/" + pending["id"]
    assert api.post(path + "/execute", headers=auth).status_code == 409
    assert (
        api.post(path + "/approval", headers=auth, json={"decision": "APPROVE"}).status_code == 403
    )
    assert (
        api.post(path + "/approval", headers=human, json={"decision": "APPROVE"}).status_code == 200
    )
    assert (
        api.post(path + "/approval", headers=human, json={"decision": "REJECT"}).status_code == 409
    )
    first = api.post(path + "/execute", headers=auth)
    assert first.status_code == 200 and first.json()["state"] == "SUCCEEDED"
    assert first.json()["effective_reason"] == "HUMAN_APPROVED"
    assert api.post(path + "/execute", headers=auth).json() == first.json()
    assert submit(api, auth, 20000, "approved")["result"] == first.json()["result"]
    assert (
        api.post(
            "/operations", json=transfer(20001), headers={**auth, "Idempotency-Key": "approved"}
        ).status_code
        == 409
    )
    rejected = submit(api, auth, 30000)
    path = "/operations/" + rejected["id"]
    assert (
        api.post(path + "/approval", headers=human, json={"decision": "REJECT"}).status_code == 200
    )
    assert api.post(path + "/execute", headers=auth).status_code == 409
    assert balances(pg_database) == {"acct-alice": 980000, "acct-bob": 1020000}
    assert api.get("/accounts", headers=auth).status_code == 403


def test_concurrent_duplicate_submission_and_execution(api, auth, human, pg_database):
    with ThreadPoolExecutor(4) as pool:
        submissions = list(pool.map(lambda _: submit(api, auth, key="race"), range(4)))
    assert len({op["id"] for op in submissions}) == 1
    path = "/operations/" + submissions[0]["id"] + "/execute"
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: api.post(path, headers=auth), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert all(r.json() == responses[0].json() for r in responses)
    assert balances(pg_database) == {"acct-alice": 999900, "acct-bob": 1000100}
    events = api.get("/audit?limit=100", headers=human).json()["events"]
    assert sum(e["event_type"] == "OPERATION_EXECUTED" for e in events) == 1


def test_distinct_concurrent_executions_conserve_funds(api, auth, pg_database):
    with psycopg.connect(pg_database) as connection:
        connection.execute("UPDATE accounts SET balance_cents=150 WHERE id='acct-alice'")
    ops = [submit(api, auth, 100) for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(lambda op: api.post("/operations/" + op["id"] + "/execute", headers=auth), ops)
        )
    assert sorted(r.status_code for r in responses) == [200, 403]
    values = balances(pg_database)
    assert values["acct-alice"] == 50 and min(values.values()) >= 0
    assert sum(values.values()) == 1000150


def test_read_isolation_consistent_snapshot_and_read_only(pg_database):
    with PostgresUnitOfWork(pg_database) as writer, closing(connect(pg_database)) as reader:
        writer.accounts.save(Account(AccountId("acct-alice"), 999999))
        writer.accounts.save(Account(AccountId("acct-bob"), 1000001))
        begin_read(reader)
        assert (
            reader.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        )
        before = reader.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        writer.commit()
        assert reader.execute("SELECT * FROM accounts ORDER BY id").fetchall() == before
        assert [row["balance_cents"] for row in before] == [1000000, 1000000]
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            reader.execute("UPDATE accounts SET balance_cents=0")
    assert balances(pg_database) == {"acct-alice": 999999, "acct-bob": 1000001}


def test_audit_failure_rolls_back_balances_result_and_approval(
    api, auth, human, pg_database, monkeypatch
):
    operation = submit(api, auth, 20000)
    path = "/operations/" + operation["id"]
    assert (
        api.post(path + "/approval", headers=human, json={"decision": "APPROVE"}).status_code == 200
    )
    original = PostgresAuditRepository.append

    def broken(self, event):
        from agentgate.domain.events.operation_executed_event import OperationExecutedEvent

        if isinstance(event, OperationExecutedEvent):
            raise StorageUnavailable
        return original(self, event)

    monkeypatch.setattr(PostgresAuditRepository, "append", broken)
    response = api.post(path + "/execute", headers=auth)
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert response.json()["state"] == "FAILED"
    assert balances(pg_database) == {"acct-alice": 1000000, "acct-bob": 1000000}
    with closing(connect(pg_database)) as connection:
        assert connection.execute("SELECT status FROM approvals").fetchone()["status"] == "GRANTED"
        assert (
            connection.execute("SELECT result_json FROM operations").fetchone()["result_json"]
            is None
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM audit_events WHERE event_type='OPERATION_EXECUTED'"
            ).fetchone()["n"]
            == 0
        )


def test_restart_components_preserve_replay(api, auth, pg_settings, pg_database):
    from fastapi.testclient import TestClient

    from agentgate.main import create_app

    operation = submit(api, auth, key="restart")
    path = "/operations/" + operation["id"] + "/execute"
    first = api.post(path, headers=auth).json()
    with TestClient(create_app(build_components(pg_settings))) as restarted:
        assert submit(restarted, auth, key="restart")["id"] == operation["id"]
        assert restarted.post(path, headers=auth).json() == first
    assert balances(pg_database)["acct-alice"] == 999900


def test_uncertain_commit_reconciles_durable_success(api, auth, pg_database, monkeypatch):
    operation = submit(api, auth)
    original = PostgresUnitOfWork.commit
    calls = 0

    def lost_ack(self):
        nonlocal calls
        calls += 1
        original(self)
        if calls == 2:
            raise CommitUncertain

    monkeypatch.setattr(PostgresUnitOfWork, "commit", lost_ack)
    path = "/operations/" + operation["id"] + "/execute"
    response = api.post(path, headers=auth)
    assert response.status_code == 200 and response.json()["state"] == "SUCCEEDED"
    assert api.post(path, headers=auth).json() == response.json()
    assert balances(pg_database)["acct-alice"] == 999900


def test_connection_loss_before_commit_rolls_back(pg_database):
    with pytest.raises(StorageUnavailable):
        with PostgresUnitOfWork(pg_database) as work:
            work.accounts.save(Account(AccountId("acct-alice"), 1))
            work._connection.close()
            work.commit()
    assert balances(pg_database)["acct-alice"] == 1000000


def test_lock_failure_confirmed_rollback_and_deadline(pg_database):
    clock = SystemClock()
    with closing(connect(pg_database)) as locker:
        locker.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
        work = PostgresUnitOfWork(pg_database)
        work.set_deadline(ExecutionDeadline(clock, clock.monotonic() + 1))
        start = clock.monotonic()
        with pytest.raises(TransientStorageLock):
            with work:
                pytest.fail("Writer lock must not be bypassed")
        assert work.rollback_confirmed and clock.monotonic() - start < 1


def test_principal_idempotency_isolation_and_direct_handler_authorization(pg_settings):
    from agentgate.application.exceptions.forbidden import Forbidden

    components = build_components(pg_settings)
    agent = components.credentials.verify(pg_settings.agent_token)
    human = components.credentials.verify(pg_settings.approver_token)
    request = OperationRequest(
        TransferArguments(AccountId("acct-alice"), AccountId("acct-bob"), Money(100))
    )
    first = components.request_operation.handle(
        RequestOperationCommand(agent, IdempotencyKey("shared"), request)
    )
    second = components.request_operation.handle(
        RequestOperationCommand(
            replace(agent, id=PrincipalId("principal-other-agent")),
            IdempotencyKey("shared"),
            request,
        )
    )
    assert first.operation.id != second.operation.id
    with pytest.raises(Forbidden):
        components.approve_operation.handle(
            ApproveOperationCommand(agent, first.operation.id, ApprovalDecision.APPROVE)
        )
    with pytest.raises(Forbidden):
        components.execute_operation.handle(ExecuteOperationCommand(human, first.operation.id))


def test_malicious_input_is_sanitized(api, auth, human, pg_settings):
    payload = transfer()
    payload["arguments"]["amount_cents"] = True
    response = api.post(
        "/operations", json=payload, headers={**auth, "Idempotency-Key": "malicious"}
    )
    assert response.status_code == 422
    response = api.post(
        "/operations",
        json={**transfer(), "role": "approver"},
        headers={**auth, "Idempotency-Key": "override"},
    )
    assert response.status_code == 422
    events = api.get("/audit", headers=human)
    assert events.json()["events"] == []
    assert pg_settings.agent_token not in response.text + events.text


def test_approval_expiry_and_read_queries_do_not_mutate(api, auth, human, pg_database):
    from datetime import UTC, datetime

    from agentgate.features.expire_approval.command import ExpireApprovalCommand
    from agentgate.features.expire_approval.handler import ExpireApprovalHandler

    operation = submit(api, auth, 20000)
    path = "/operations/" + operation["id"]
    snapshot = api.get(path, headers=auth).json()
    with closing(connect(pg_database)) as connection:
        before = connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    assert api.get(path, headers=auth).json() == snapshot
    with closing(connect(pg_database)) as connection:
        assert connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall() == before

    class ExpiredClock:
        def now(self):
            return datetime.now(UTC) + timedelta(seconds=301)

        def monotonic(self):
            return 0.0

    ExpireApprovalHandler(lambda: PostgresUnitOfWork(pg_database), ExpiredClock()).handle(
        ExpireApprovalCommand(OperationId(operation["id"]))
    )
    assert api.get(path, headers=auth).json()["state"] == "EXPIRED"
    assert api.post(path + "/execute", headers=auth).status_code == 409


def test_deadline_before_commit_rolls_back_without_late_effect(pg_database):
    from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut

    class Clock:
        elapsed = 0.0

        def monotonic(self):
            return self.elapsed

        def now(self):
            return SystemClock().now()

    clock = Clock()
    work = PostgresUnitOfWork(pg_database)
    work.set_deadline(ExecutionDeadline(clock, 2.0))
    with pytest.raises(ExecutionTimedOut), work:
        work.accounts.save(Account(AccountId("acct-alice"), 1))
        clock.elapsed = 2.0
        work.commit()
    assert work.rollback_confirmed
    assert balances(pg_database) == {"acct-alice": 1000000, "acct-bob": 1000000}


def test_uncertain_uncommitted_attempt_requires_later_explicit_execution(
    api, auth, pg_database, monkeypatch
):
    operation = submit(api, auth)
    original = PostgresUnitOfWork.commit
    calls = 0

    def no_ack(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            # Simulate a connection failure before COMMIT reached the server.
            # The caller cannot know this and must reconcile rather than redispatch.
            self._commit_started = True
            raise CommitUncertain
        original(self)

    monkeypatch.setattr(PostgresUnitOfWork, "commit", no_ack)
    path = "/operations/" + operation["id"] + "/execute"
    assert api.post(path, headers=auth).status_code == 503
    assert balances(pg_database) == {"acct-alice": 1000000, "acct-bob": 1000000}
    assert api.get("/operations/" + operation["id"], headers=auth).json()["state"] == "READY"
    response = api.post(path, headers=auth)
    assert response.status_code == 200 and response.json()["state"] == "SUCCEEDED"
    assert balances(pg_database)["acct-alice"] == 999900


def test_competing_human_decisions_commit_once(api, auth, human, pg_database):
    operation = submit(api, auth, 20000)
    path = "/operations/" + operation["id"] + "/approval"
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(
                lambda decision: api.post(path, headers=human, json={"decision": decision}),
                ["APPROVE", "REJECT"],
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert balances(pg_database) == {"acct-alice": 1000000, "acct-bob": 1000000}
    events = api.get("/audit?limit=100", headers=human).json()["events"]
    assert sum(event["event_type"] == "APPROVAL_DECIDED" for event in events) == 1


def test_opposite_transfers_conserve_total_without_lost_updates(pg_settings, pg_database):
    components = build_components(pg_settings)
    alice = components.credentials.verify(pg_settings.agent_token)
    bob = replace(
        alice, id=PrincipalId("principal-bob"), source_accounts=frozenset({AccountId("acct-bob")})
    )
    requests = [
        (alice, TransferArguments(AccountId("acct-alice"), AccountId("acct-bob"), Money(100))),
        (bob, TransferArguments(AccountId("acct-bob"), AccountId("acct-alice"), Money(200))),
    ]

    # Trusted principals are injected for this isolated handler test; no new credentials.
    class Principals:
        def get_principal(self, id):
            return next((principal for principal in (alice, bob) if principal.id == id), None)

    components.execute_operation._principals = Principals()
    operations = [
        (
            principal,
            components.request_operation.handle(
                RequestOperationCommand(
                    principal, IdempotencyKey(str(uuid4())), OperationRequest(args)
                )
            ).operation,
        )
        for principal, args in requests
    ]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda pair: components.execute_operation.handle(
                    ExecuteOperationCommand(pair[0], pair[1].id)
                ),
                operations,
            )
        )
    assert all(result.operation.state.value == "SUCCEEDED" for result in results)
    values = balances(pg_database)
    assert values == {"acct-alice": 1000100, "acct-bob": 999900}
    assert sum(values.values()) == 2000000
