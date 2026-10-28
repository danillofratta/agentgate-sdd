"""Deterministic task 5.4 transaction deadlines, rollback and retry faults."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.infrastructure.persistence.database import connect
from agentgate.infrastructure.persistence.deadline_connection import DeadlineConnection
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from tests.infrastructure.execution_assertions import assert_rolled_back
from tests.infrastructure.test_concurrent_execution_recovery import CountingTools, snapshot
from tests.infrastructure.test_secure_transfer_execution import persist_transfer


def lock_error(code=sqlite3.SQLITE_BUSY):
    error = sqlite3.OperationalError("private adapter details")
    error.sqlite_errorcode = code
    return error


def executor(database, principal, clock, *, factory=None, tools=None, sleep=None, principals=None):
    return ExecuteOperationHandler(
        factory or (lambda: SqliteUnitOfWork(database)),
        tools or CountingTools(),
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=sleep or (lambda _: pytest.fail("unexpected retry"))),
        principals or SimpleNamespace(get_principal=lambda _: principal),
        recovery_unit_of_work=lambda: SqliteUnitOfWork(database),
    )


def hook(work, boundary, callback):
    """Run a fault immediately after a chosen transactional effect."""
    if boundary in ("debit", "credit"):
        target, method = work.accounts, "save"
    elif boundary == "result":
        target, method = work.operations, "save_execution"
    elif boundary == "approval":
        target, method = work.approvals, "save_consumption"
    else:
        target, method = work.audit, "append"
    original = getattr(target, method)
    count = 0

    def wrapped(*args):
        nonlocal count
        original(*args)
        count += 1
        matches = (
            (boundary == "debit" and count == 1)
            or (boundary == "credit" and count == 2)
            or boundary in ("result", "approval")
            or (boundary == "dispatch_audit" and isinstance(args[0], OperationDispatchedEvent))
            or (boundary == "success_audit" and isinstance(args[0], OperationExecutedEvent))
        )
        if matches:
            callback()

    setattr(target, method, wrapped)


@pytest.mark.parametrize("approved", [False, True])
def test_success_inside_budget_and_wall_time_independence(database, principal, clock, approved):
    operation = persist_transfer(database, principal, clock, approved)
    tools = CountingTools()
    dispatch = tools.dispatch

    def advance(*args):
        clock.elapsed = 1.999
        clock.value += timedelta(days=1)
        return dispatch(*args)

    tools.dispatch = advance
    result = executor(database, principal, clock, tools=tools).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED
    assert len(tools.calls) == 1


@pytest.mark.parametrize(
    "boundary",
    [
        "dispatch_audit",
        "dispatch",
        "debit",
        "credit",
        "result",
        "approval",
        "success_audit",
        "commit",
    ],
)
def test_timeout_rolls_back_every_effect_and_closes_connection(
    database, principal, clock, boundary
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()
    connections = []
    attempts = []

    def expire():
        clock.elapsed = 2.0

    class ExpiringWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            connections.append(self._connection)
            if boundary not in ("dispatch", "commit"):
                hook(self, boundary, expire)
            return self

        def commit(self):
            if boundary == "commit":
                expire()
            super().commit()

    if boundary == "dispatch":
        dispatch = tools.dispatch

        def expired_dispatch(*args):
            expire()
            return dispatch(*args)

        tools.dispatch = expired_dispatch
    with pytest.raises(ExecutionTimedOut):
        executor(
            database, principal, clock, tools=tools, factory=lambda: ExpiringWork(database)
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(attempts) == 1
    assert len(tools.calls) == (0 if boundary == "dispatch_audit" else 1)
    assert_rolled_back(database, before, state="TIMED_OUT")
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            sqlite3.Connection.execute(connection, "UPDATE accounts SET balance_cents=0")
    clock.elapsed += 100
    assert_rolled_back(database, before, state="TIMED_OUT")


def test_deadline_before_first_attempt_never_opens_transaction(database, principal, clock):
    operation = persist_transfer(database, principal, clock, False)
    readings = iter([0.0, 2.0])
    clock.monotonic = lambda: next(readings, 2.0)
    before = snapshot(database)
    with pytest.raises(ExecutionTimedOut):
        executor(database, principal, clock, factory=lambda: pytest.fail("late attempt")).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert_rolled_back(database, before, state="TIMED_OUT", attempts=0)


@pytest.mark.parametrize(
    "code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY | (2 << 8)]
)
@pytest.mark.parametrize(
    "boundary", ["dispatch_audit", "debit", "credit", "result", "approval", "success_audit"]
)
def test_only_rolled_back_locks_retry_and_replay_one_durable_effect(
    database, principal, clock, code, boundary
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    attempts, delays, connections, deadlines = [], [], [], []
    tools = CountingTools()

    class LockingWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            connections.append(self._connection)
            deadlines.append(self._deadline)
            if len(attempts) == 1:
                hook(self, boundary, lambda: (_ for _ in ()).throw(lock_error(code)))
            return self

    def sleep(seconds):
        assert attempts[0]._connection is None  # rollback and close precede delay
        assert_rolled_back(database, before)
        assert 0 < seconds <= 0.05
        delays.append(seconds)
        clock.elapsed += seconds

    run = executor(
        database, principal, clock, factory=lambda: LockingWork(database), tools=tools, sleep=sleep
    )
    result = run.handle(ExecuteOperationCommand(principal, operation.id))
    assert result.operation.state == OperationState.SUCCEEDED
    assert len(attempts) == 2 and delays == [0.05]
    assert deadlines[0] is deadlines[1] and deadlines[0].expires_at == 2.0
    after = snapshot(database)
    assert run.handle(ExecuteOperationCommand(principal, operation.id)) == result
    assert snapshot(database) == after
    assert len(tools.calls) == (1 if boundary == "dispatch_audit" else 2)
    with closing(connect(database)) as connection:
        assert (
            connection.execute("SELECT balance_cents FROM accounts ORDER BY id").fetchall()[0][0]
            == 989999
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='OPERATION_EXECUTED'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("remaining", [2.0, 0.02])
def test_retry_exhaustion_and_single_delay_with_original_deadline(
    database, principal, clock, remaining
):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    attempts, delays = [], []
    tools = CountingTools()

    def fail():
        clock.elapsed = 2.0 - remaining
        raise lock_error()

    class LockedWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            hook(self, "debit", fail)
            return self

    def sleep(seconds):
        delays.append(seconds)
        clock.elapsed += seconds

    with pytest.raises(TransientStorageLock if remaining == 2 else ExecutionTimedOut):
        executor(
            database,
            principal,
            clock,
            factory=lambda: LockedWork(database),
            tools=tools,
            sleep=sleep,
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(delays) == 1 and 0 < delays[0] <= 0.05
    assert len(attempts) == len(tools.calls) == (2 if remaining == 2 else 1)
    assert_rolled_back(
        database,
        before,
        state="FAILED" if remaining == 2 else "TIMED_OUT",
        attempts=2 if remaining == 2 else 1,
    )


@pytest.mark.parametrize("changed", ["permissions", "funds", "expiry", "ownership", "policy"])
def test_retry_reloads_authorization_funds_approval_owner_and_policy(
    database, principal, clock, changed
):
    operation = persist_transfer(database, principal, clock, True)
    attempts, delays = [], []
    tools = CountingTools()
    current = principal
    expected = []

    class FirstLock(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            if len(attempts) == 1:
                hook(self, "debit", lambda: (_ for _ in ()).throw(lock_error()))
            return self

    def sleep(seconds):
        nonlocal current
        delays.append(seconds)
        assert attempts[0]._connection is None
        clock.elapsed += seconds
        if changed == "permissions":
            current = replace(principal, tools=frozenset())
        elif changed == "expiry":
            clock.value += timedelta(seconds=300)
        else:
            with closing(connect(database)) as connection:
                if changed == "funds":
                    connection.execute("UPDATE accounts SET balance_cents=1 WHERE id='acct-alice'")
                elif changed == "ownership":
                    connection.execute("UPDATE operations SET principal_id='principal-other'")
                else:
                    connection.execute("UPDATE operations SET policy_version='v2'")
        expected.append(snapshot(database))

    with pytest.raises(
        InvalidTransition
        if changed == "expiry"
        else NotFound
        if changed == "ownership"
        else Forbidden
    ):
        executor(
            database,
            principal,
            clock,
            factory=lambda: FirstLock(database),
            tools=tools,
            sleep=sleep,
            principals=SimpleNamespace(get_principal=lambda _: current),
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(attempts) == 1 and len(delays) == 1 and len(tools.calls) == 1
    assert snapshot(database) == expected[0]


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unknown"),
        sqlite3.OperationalError("untyped"),
        lock_error(sqlite3.SQLITE_IOERR),
    ],
)
def test_unknown_nonretryable_errors_dispatch_once(database, principal, clock, error):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()
    attempts = []

    class BrokenWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            hook(self, "credit", lambda: (_ for _ in ()).throw(error))
            return self

    with pytest.raises(
        StorageUnavailable if isinstance(error, sqlite3.Error) else ExecutionUnavailable
    ):
        executor(
            database, principal, clock, factory=lambda: BrokenWork(database), tools=tools
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(attempts) == len(tools.calls) == 1
    assert_rolled_back(database, before, state="FAILED")


@pytest.mark.parametrize("committed", [False, True])
def test_uncertain_commit_never_retried_even_if_lock_shaped(database, principal, clock, committed):
    operation = persist_transfer(database, principal, clock, True)
    tools = CountingTools()
    attempts = []

    class UncertainWork(SqliteUnitOfWork):
        def commit(self):
            attempts.append(self)
            if committed:
                super().commit()
            self._commit_started = True
            raise lock_error()

    run = executor(database, principal, clock, factory=lambda: UncertainWork(database), tools=tools)
    if committed:
        result = run.handle(ExecuteOperationCommand(principal, operation.id))
        assert result.operation.state == OperationState.SUCCEEDED
    else:
        with pytest.raises(StorageUnavailable):
            run.handle(ExecuteOperationCommand(principal, operation.id))
    assert len(attempts) == len(tools.calls) == 1


def test_delayed_confirmed_commit_is_success(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)

    class SlowAcknowledgment(SqliteUnitOfWork):
        def commit(self):
            super().commit()
            clock.elapsed = 100.0

    result = executor(
        database, principal, clock, factory=lambda: SlowAcknowledgment(database)
    ).handle(ExecuteOperationCommand(principal, operation.id))
    assert result.operation.state == OperationState.SUCCEEDED


@pytest.mark.parametrize("remaining", [1.0, 0.0129, 0.0001])
def test_adapter_busy_timeout_is_floor_of_remaining_or_50ms(database, clock, remaining):
    transaction = SqliteUnitOfWork(database)
    transaction.set_deadline(ExecutionDeadline(clock, remaining))
    with transaction as work:
        connection = work._connection
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == int(
            min(remaining, 0.05) * 1000
        )


def test_progress_interrupt_rolls_back_and_stops_statement(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    work = SqliteUnitOfWork(database)
    work.set_deadline(ExecutionDeadline(clock, 2.0))
    with pytest.raises(ExecutionTimedOut):
        with work:
            connection = work._connection
            connection.execute("UPDATE accounts SET balance_cents=1")
            reads = 0

            def ticking():
                nonlocal reads
                reads += 1
                return 2.0 if reads >= 5 else 0.0

            clock.monotonic = ticking
            connection.execute(
                "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL "
                "SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n"
            ).fetchone()
    assert reads <= 6
    assert work._connection is None and snapshot(database) == before
    assert operation.state == OperationState.READY


def test_begin_lock_is_classified_only_after_rollback(database, principal, clock, monkeypatch):
    operation = persist_transfer(database, principal, clock, False)
    attempts, delays = [], []
    original = DeadlineConnection.execute

    def execute(connection, sql, parameters=()):
        if sql == "BEGIN IMMEDIATE" and getattr(connection, "execution_fault", False):
            attempts.append(connection)
            if len(attempts) == 1:
                raise lock_error()
        return original(connection, sql, parameters)

    def sleep(seconds):
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            attempts[0].execute("SELECT 1")
        delays.append(seconds)
        clock.elapsed += seconds

    class BeginLockWork(SqliteUnitOfWork):
        def set_deadline(self, deadline):
            super().set_deadline(deadline)

        def __enter__(self):
            original_connect = connect

            def tagged_connect(path):
                connection = original_connect(path)
                connection.execution_fault = True
                return connection

            with monkeypatch.context() as patch:
                patch.setattr(
                    "agentgate.infrastructure.persistence.sqlite_unit_of_work.connect",
                    tagged_connect,
                )
                return super().__enter__()

    monkeypatch.setattr(DeadlineConnection, "execute", execute)
    result = executor(
        database, principal, clock, sleep=sleep, factory=lambda: BeginLockWork(database)
    ).handle(ExecuteOperationCommand(principal, operation.id))
    assert result.operation.state == OperationState.SUCCEEDED
    assert len(attempts) == 2 and delays == [0.05]


def test_failed_rollback_never_becomes_retryable(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()

    class RollbackFailure(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            hook(self, "debit", lambda: (_ for _ in ()).throw(lock_error()))
            return self

        def rollback(self):
            raise StorageUnavailable

    with pytest.raises(StorageUnavailable) as caught:
        executor(
            database, principal, clock, factory=lambda: RollbackFailure(database), tools=tools
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert type(caught.value) is StorageUnavailable and len(tools.calls) == 1
    assert_rolled_back(database, before)


def test_deadline_before_first_mutation_has_no_audit_or_dispatch(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()
    run = executor(database, principal, clock, tools=tools)
    evaluate = run._harness._policy.evaluate

    def expires_during_policy(facts):
        result = evaluate(facts)
        clock.elapsed = 2.0
        return result

    run._harness._policy = SimpleNamespace(evaluate=expires_during_policy)
    with pytest.raises(ExecutionTimedOut):
        run.handle(ExecuteOperationCommand(principal, operation.id))
    assert tools.calls == []
    assert_rolled_back(database, before, state="TIMED_OUT", attempts=0)


def test_adapter_rechecks_deadline_after_harness_mutation_check(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    tools = CountingTools()

    class DelayedRepository(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            save = self.accounts.save

            def late_save(account):
                clock.elapsed = 2.0
                save(account)

            self.accounts.save = late_save
            return self

    with pytest.raises(ExecutionTimedOut):
        executor(
            database, principal, clock, tools=tools, factory=lambda: DelayedRepository(database)
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(tools.calls) == 1
    assert_rolled_back(database, before, state="TIMED_OUT")


def test_real_sqlite_busy_attempt_audit_failure_prevents_dispatch(database, principal, clock):
    operation = persist_transfer(database, principal, clock, False)
    lock = connect(database)
    lock.execute("BEGIN IMMEDIATE")
    tools = CountingTools()

    class ZeroWait(SqliteUnitOfWork):
        def set_deadline(self, deadline):
            super().set_deadline(deadline)
            clock.elapsed = 1.9999

    run = executor(database, principal, clock, tools=tools)
    run._recovery_work = lambda: ZeroWait(database)
    try:
        with pytest.raises(StorageUnavailable):
            run.handle(ExecuteOperationCommand(principal, operation.id))
    finally:
        lock.close()
    assert tools.calls == []
    with SqliteUnitOfWork(database) as work:
        assert work.operations.get(operation.id) == operation


def test_second_attempt_still_expires_at_original_deadline(database, principal, clock):
    operation = persist_transfer(database, principal, clock, True)
    before = snapshot(database)
    attempts, delays = [], []
    tools = CountingTools()
    dispatch = tools.dispatch

    def dispatch_with_cost(*args):
        clock.elapsed += 0.03
        return dispatch(*args)

    tools.dispatch = dispatch_with_cost

    def lock_near_deadline():
        clock.elapsed = 1.94
        raise lock_error()

    class FirstLock(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            attempts.append(self)
            if len(attempts) == 1:
                hook(self, "debit", lock_near_deadline)
            return self

    def sleep(seconds):
        delays.append(seconds)
        clock.elapsed += seconds

    with pytest.raises(ExecutionTimedOut):
        executor(
            database,
            principal,
            clock,
            tools=tools,
            factory=lambda: FirstLock(database),
            sleep=sleep,
        ).handle(ExecuteOperationCommand(principal, operation.id))
    assert len(attempts) == len(tools.calls) == 2 and delays == [0.05]
    assert_rolled_back(database, before, state="TIMED_OUT", attempts=2)


def test_actual_commit_crossing_deadline_keeps_progress_cancellation_disabled(
    database, principal, clock, monkeypatch
):
    operation = persist_transfer(database, principal, clock, True)
    commit = DeadlineConnection.commit

    def delayed_commit(connection):
        if connection.execute("SELECT state FROM operations").fetchone()[0] == "SUCCEEDED":
            clock.elapsed = 2.1
        commit(connection)

    monkeypatch.setattr(DeadlineConnection, "commit", delayed_commit)
    result = executor(database, principal, clock).handle(
        ExecuteOperationCommand(principal, operation.id)
    )
    assert result.operation.state == OperationState.SUCCEEDED


def test_begin_rollback_failure_is_not_classified_transient(
    database, principal, clock, monkeypatch
):
    operation = persist_transfer(database, principal, clock, False)
    execute = DeadlineConnection.execute
    attempts = []

    def locked(connection, sql, parameters=()):
        if sql == "BEGIN IMMEDIATE":
            attempts.append(connection)
            raise lock_error()
        return execute(connection, sql, parameters)

    def broken_rollback(connection):
        raise sqlite3.OperationalError("rollback not confirmed")

    monkeypatch.setattr(DeadlineConnection, "execute", locked)
    monkeypatch.setattr(DeadlineConnection, "rollback", broken_rollback)
    with pytest.raises(StorageUnavailable) as caught:
        executor(database, principal, clock).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert type(caught.value) is StorageUnavailable and len(attempts) == 1
