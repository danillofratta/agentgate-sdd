"""Task 5.5: durable evidence and recovery across independent SQLite connections."""

import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.domain.events.operation_attempted_event import OperationAttemptedEvent
from agentgate.domain.events.operation_failed_event import OperationFailedEvent
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.role import Role
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.list_audit.endpoint import list_audit
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.infrastructure.persistence.database import V5_SCHEMA, connect, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from agentgate.transport.configure import configure_http
from tests.infrastructure.execution_assertions import assert_rolled_back
from tests.infrastructure.test_concurrent_execution_recovery import CountingTools, snapshot
from tests.infrastructure.test_execution_deadline_retry import executor, hook, lock_error
from tests.infrastructure.test_secure_transfer_execution import persist_transfer


def evidence(database):
    return SqliteAuditReadRepository(database).list(AuditPage(limit=100))


def attempts(database):
    return [
        record.event
        for record in evidence(database)
        if isinstance(record.event, OperationAttemptedEvent)
    ]


@pytest.mark.parametrize(
    "outcome,count", [("retry_success", 2), ("locks_exhausted", 2), ("nonretryable", 1)]
)
def test_evidence_precedes_each_attempt_and_exact_2_2_1_counts(
    database, principal, clock, outcome, count
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()
    dispatch = tools.dispatch
    entered, delays = [], []

    class FaultWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            entered.append(self)
            # Independent readers see committed evidence before any tool call.
            assert [event.attempt for event in attempts(database)] == list(
                range(1, len(entered) + 1)
            )
            if outcome != "retry_success" or len(entered) == 1:

                def fail():
                    if outcome == "nonretryable":
                        raise RuntimeError("SECRET_SENTINEL\nforged-log")
                    raise lock_error()

                hook(self, "credit", fail)
            return self

    def checked_dispatch(*args):
        assert len(attempts(database)) == len(entered)
        assert attempts(database)[-1].operation_id == operation.id
        return dispatch(*args)

    def sleep(seconds):
        assert entered[-1]._connection is None
        assert_rolled_back(database, before)
        delays.append(seconds)
        clock.elapsed += seconds

    tools.dispatch = checked_dispatch
    run = executor(
        database, principal, clock, factory=lambda: FaultWork(database), tools=tools, sleep=sleep
    )
    command = ExecuteOperationCommand(principal, operation.id)
    if outcome == "retry_success":
        result = run.handle(command)
        assert result.operation.state == OperationState.SUCCEEDED
    else:
        with pytest.raises(TransientStorageLock if count == 2 else ExecutionUnavailable) as caught:
            run.handle(command)
        assert "SECRET_SENTINEL" not in str(caught.value)
        assert_rolled_back(database, before, state="FAILED", attempts=count)
    assert len(entered) == len(tools.calls) == len(attempts(database)) == count
    assert delays == ([0.05] if count == 2 else [])
    assert [event.attempt for event in attempts(database)] == list(range(1, count + 1))


@pytest.mark.parametrize("boundary", ["append", "commit", "uncertain_commit", "factory"])
def test_attempt_evidence_failure_prevents_dispatch_and_fabricated_terminal_state(
    database, principal, clock, boundary
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()

    class AuditFailure(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            if boundary == "append":

                def fail(*_):
                    raise RuntimeError("SECRET_SENTINEL\nSQL credentials")

                self.audit.append_attempt = fail
            return self

        def commit(self):
            if boundary == "uncertain_commit":
                super().commit()
            raise StorageUnavailable

    def recovery():
        if boundary == "factory":
            raise RuntimeError("SECRET_SENTINEL")
        return AuditFailure(database)

    run = executor(database, principal, clock, tools=tools)
    run._recovery_work = recovery
    with pytest.raises(StorageUnavailable) as caught:
        run.handle(ExecuteOperationCommand(principal, operation.id))
    assert str(caught.value) == "" and tools.calls == []
    if boundary == "uncertain_commit":
        assert_rolled_back(database, before)
    else:
        assert snapshot(database) == before
    # A fresh call must consult durable state, including evidence already committed.
    result = executor(database, principal, clock).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED
    assert [event.attempt for event in attempts(database)] == (
        [1, 2] if boundary == "uncertain_commit" else [1]
    )


@pytest.mark.parametrize("timed_out", [False, True])
@pytest.mark.parametrize("approved", [False, True])
def test_terminal_failure_reopen_replay_identity_and_approval_preservation(
    database, principal, clock, timed_out, approved
):
    operation = persist_transfer(database, principal, clock, approved)
    before = snapshot(database)
    tools = CountingTools()

    class FailedWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()

            def fail():
                if timed_out:
                    clock.elapsed = 2.0
                    raise ExecutionTimedOut
                raise ExecutionUnavailable

            hook(self, "success_audit", fail)
            return self

    error = ExecutionTimedOut if timed_out else ExecutionUnavailable
    state = "TIMED_OUT" if timed_out else "FAILED"
    with pytest.raises(error):
        executor(
            database, principal, clock, tools=tools, factory=lambda: FailedWork(database)
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert_rolled_back(database, before, state=state)
    initialize(database)
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == operation.transition(OperationState(state))
    assert stored.result is None
    with SqliteUnitOfWork(database) as work:
        assert work.operations.find(operation.principal_id, operation.key) == stored.operation
        if approved:
            assert work.approvals.get(operation.id).state == ApprovalState.GRANTED
    after = snapshot(database)
    for _ in range(3):
        with pytest.raises(error):
            executor(database, principal, clock, tools=tools).handle(
                ExecuteOperationCommand(principal, operation.id)
            )
    assert len(tools.calls) == 1 and snapshot(database) == after
    response = list_audit(
        replace(principal, role=Role.APPROVER),
        ListAuditHandler(SqliteAuditReadRepository(database)),
        0,
        100,
    )
    assert response.events[-1].decision == state
    assert response.events[-1].reason == "EXECUTION_" + state
    assert response.events[-2].attempt == 1


@pytest.mark.parametrize(
    "boundary", ["state", "audit", "commit", "deadline", "factory", "uncertain_commit"]
)
def test_terminal_recording_failure_never_claims_durability(database, principal, clock, boundary):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()

    class ExecutionFailure(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            hook(self, "success_audit", lambda: (_ for _ in ()).throw(ExecutionUnavailable()))
            return self

    class TerminalFailure(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()

            def fail(*_):
                raise RuntimeError("SECRET_SENTINEL")

            if boundary == "state":
                self.operations.save_failure = fail
            elif boundary == "audit":
                self.audit.append = fail
            elif boundary == "deadline":
                clock.elapsed += 0.05
            return self

        def commit(self):
            if boundary == "uncertain_commit":
                super().commit()
            if boundary in ("commit", "uncertain_commit"):
                raise StorageUnavailable
            super().commit()

    calls = 0

    def recovery():
        nonlocal calls
        calls += 1
        if calls == 1:
            return SqliteUnitOfWork(database)
        if boundary == "factory":
            raise RuntimeError("SECRET_SENTINEL")
        return TerminalFailure(database)

    run = executor(
        database, principal, clock, tools=tools, factory=lambda: ExecutionFailure(database)
    )
    run._recovery_work = recovery
    with pytest.raises(StorageUnavailable) as caught:
        run.handle(ExecuteOperationCommand(principal, operation.id))
    assert str(caught.value) == "" and len(tools.calls) == 1
    assert_rolled_back(
        database, before, state="FAILED" if boundary == "uncertain_commit" else "READY"
    )


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("available", [False, True])
def test_uncertain_commit_reopens_authoritative_state_without_redispatch(
    database, principal, clock, committed, available
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()

    class UncertainWork(SqliteUnitOfWork):
        def commit(self):
            if committed:
                super().commit()
            self._commit_started = True
            raise lock_error()  # Even a lock-shaped commit error is uncertain.

    reopened = []

    class RecoveryWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            reopened.append(self.operations.get(operation.id).state)
            if len(reopened) > 1 and not available:
                # Raise inside the body instead of leaking a connection from __enter__.
                self.operations.get = lambda _: (_ for _ in ()).throw(StorageUnavailable())
            return self

    run = executor(database, principal, clock, tools=tools, factory=lambda: UncertainWork(database))
    run._recovery_work = lambda: RecoveryWork(database)
    command = ExecuteOperationCommand(principal, operation.id)
    if committed and available:
        result = run.handle(command)
        assert result.operation.state == OperationState.SUCCEEDED
    else:
        with pytest.raises(StorageUnavailable) as caught:
            run.handle(command)
        assert str(caught.value) == ""
    assert len(reopened) == 2 and len(tools.calls) == 1
    if not committed:
        assert_rolled_back(database, before)
    # Restart sees authoritative state. Only positively confirmed rollback permits dispatch.
    result = executor(database, principal, clock, tools=tools).handle(command)
    assert result.operation.state == OperationState.SUCCEEDED
    assert len(tools.calls) == (1 if committed else 2)
    assert len(attempts(database)) == (1 if committed else 2)


def test_storage_unavailable_has_sanitized_503_semantics_without_execution_endpoint(
    database, principal, clock
):
    operation = persist_transfer(database, principal, clock, False)
    before = snapshot(database)
    tools = CountingTools()
    run = executor(database, principal, clock, tools=tools)
    run._recovery_work = lambda: (_ for _ in ()).throw(RuntimeError("SECRET_SENTINEL\nSQL"))
    application = FastAPI()
    configure_http(application)

    @application.get("/fault")
    def fault():
        run.handle(ExecuteOperationCommand(principal, operation.id))

    with TestClient(application) as client:
        response = client.get("/fault")
    assert response.status_code == 503
    assert response.json() == {"error": "STORAGE_UNAVAILABLE"}
    assert tools.calls == [] and snapshot(database) == before


def test_attempt_repository_rejects_fabrication_and_database_rejects_duplicate_number(
    database, principal, clock
):
    operation = persist_transfer(database, principal, clock, False)
    with SqliteUnitOfWork(database) as work:
        event = work.audit.append_attempt(operation, clock.now())
        work.commit()
    before = snapshot(database)
    with pytest.raises(StorageUnavailable):
        with SqliteUnitOfWork(database) as work:
            work.audit.append(event)
    with pytest.raises(StorageUnavailable):
        with SqliteUnitOfWork(database) as work:
            work.audit.append_attempt(
                replace(operation, key=type(operation.key)("fabricated")), clock.now()
            )
    with closing(connect(database)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO audit_events(operation_id, principal_id, tool, decision,
                   reason, policy_version, occurred_at, event_type, fingerprint, attempt)
                   SELECT operation_id, principal_id, tool, decision, reason, policy_version,
                   occurred_at, event_type, fingerprint, attempt
                   FROM audit_events WHERE attempt=1"""
            )
    assert snapshot(database) == before


def test_v5_schema_migration_preserves_data_and_reopens(tmp_path, principal, clock):
    database = str(tmp_path / "v5.sqlite")
    with closing(connect(database)) as connection:
        for statement in V5_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=5")
        connection.execute(
            "INSERT INTO accounts VALUES ('acct-alice',1000000),('acct-bob',1000000)"
        )
    operation = persist_transfer(database, principal, clock, True)
    before = SqliteOperationReadRepository(database).get(operation.id)
    initialize(database)
    initialize(database)
    assert SqliteOperationReadRepository(database).get(operation.id) == before
    assert all(record.event.operation_id == operation.id for record in evidence(database))
    result = executor(database, principal, clock).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED


def test_terminal_recorder_replays_concurrent_success_without_overwriting_it(
    database, principal, clock
):
    operation = persist_transfer(database, principal, clock, True)
    failed_tools, winning_tools = CountingTools(), CountingTools()

    class FailedWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            hook(self, "success_audit", lambda: (_ for _ in ()).throw(ExecutionUnavailable()))
            return self

    recoveries = 0
    winner = None

    def recovery():
        nonlocal recoveries, winner
        recoveries += 1
        if recoveries == 2:
            winner = executor(database, principal, clock, tools=winning_tools).handle(
                ExecuteOperationCommand(principal, operation.id)
            )
        return SqliteUnitOfWork(database)

    run = executor(
        database, principal, clock, tools=failed_tools, factory=lambda: FailedWork(database)
    )
    run._recovery_work = recovery
    result = run.handle(ExecuteOperationCommand(principal, operation.id))
    assert result == winner and result.operation.state == OperationState.SUCCEEDED
    assert len(failed_tools.calls) == len(winning_tools.calls) == 1
    assert not any(isinstance(record.event, OperationFailedEvent) for record in evidence(database))
    with closing(connect(database)) as connection:
        assert [
            row[0] for row in connection.execute("SELECT balance_cents FROM accounts ORDER BY id")
        ] == [989999, 1010001]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='OPERATION_EXECUTED'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_actual_commit_acknowledgment_loss_after_deadline_recovers_success(
    database, principal, clock, monkeypatch, rollback_fails
):
    from agentgate.infrastructure.persistence.deadline_connection import DeadlineConnection

    operation = persist_transfer(database, principal, clock, True)
    tools = CountingTools()
    commit = DeadlineConnection.commit

    def lost_ack(connection):
        succeeded = (
            sqlite3.Connection.execute(connection, "SELECT state FROM operations").fetchone()[0]
            == "SUCCEEDED"
        )
        commit(connection)
        if succeeded:
            clock.elapsed = 3.0
            raise sqlite3.OperationalError("SECRET_SENTINEL: commit acknowledgment lost")

    class ExecutionWork(SqliteUnitOfWork):
        def rollback(self):
            if rollback_fails and self._commit_started:
                raise StorageUnavailable
            super().rollback()

    monkeypatch.setattr(DeadlineConnection, "commit", lost_ack)
    result = executor(
        database, principal, clock, tools=tools, factory=lambda: ExecutionWork(database)
    ).handle(ExecuteOperationCommand(principal, operation.id))
    assert result.operation.state == OperationState.SUCCEEDED
    assert len(tools.calls) == len(attempts(database)) == 1
    assert not any(isinstance(record.event, OperationFailedEvent) for record in evidence(database))
