"""Task 5.3: real SQLite transactions, synchronized callers, and commit fault injection."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from threading import Barrier, Lock, local
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.execute_operation.result import ExecuteOperationResult
from agentgate.infrastructure.persistence import sqlite_unit_of_work
from agentgate.infrastructure.persistence.database import connect
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.application.test_secure_transfer_handler import grant, transfer_operation
from tests.infrastructure.execution_assertions import assert_rolled_back
from tests.infrastructure.test_balance_execution import balances, registry
from tests.infrastructure.test_secure_transfer_execution import persist_transfer


def snapshot(database):
    with closing(connect(database)) as connection:
        return tuple(connection.iterdump())


class CountingTools:
    def __init__(self):
        self.calls = []
        self._lock = Lock()
        self._registry = registry()

    def dispatch(self, tool, arguments, accounts):
        with self._lock:
            self.calls.append(arguments)
        return self._registry.dispatch(tool, arguments, accounts)


def handler(database, principal, clock, tools, factory=None):
    return ExecuteOperationHandler(
        factory or (lambda: SqliteUnitOfWork(database)),
        tools,
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=lambda _: pytest.fail("unexpected retry")),
        SimpleNamespace(get_principal=lambda _: principal),
        recovery_unit_of_work=lambda: SqliteUnitOfWork(database),
    )


def execution_events(database, event_type):
    return [
        record.event
        for record in SqliteAuditReadRepository(database).list(AuditPage())
        if isinstance(record.event, event_type)
    ]


def race(database, principal, clock, operations, monkeypatch):
    """Both connections reach BEGIN before either may acquire the write lock."""
    barrier = Barrier(2, timeout=10)
    connections = []
    worker = local()
    tools = CountingTools()

    def synchronized_connect(path):
        connection = connect(path)
        # Test synchronization/scheduling allowance, not a runtime retry or lock budget.
        connection.execute("PRAGMA busy_timeout=10000")
        connections.append(connection)
        worker.connection = connection
        try:
            if not getattr(worker, "started", False):
                worker.started = True
                barrier.wait()
        except BaseException:
            connection.close()
            raise
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite_unit_of_work, "connect", synchronized_connect)
        handlers = [handler(database, principal, clock, tools) for _ in operations]

        def execute(index):
            try:
                return handlers[index].handle(
                    ExecuteOperationCommand(principal, operations[index].id)
                )
            except Forbidden as error:
                return error
            finally:
                # SQLite enforces thread affinity even for a closed connection.
                with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                    worker.connection.execute("SELECT 1")

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(execute, range(2)))
    assert len(connections) >= 3
    assert len({id(connection) for connection in connections}) == len(connections)
    return outcomes, tools


def assert_restart_replay(database, principal, clock, operation, expected):
    # All prior UoWs/read repositories close their connections before returning.
    before = snapshot(database)

    def no_dispatch(*_):
        pytest.fail("restart replay dispatched a tool")

    restarted = handler(database, principal, clock, SimpleNamespace(dispatch=no_dispatch))
    assert restarted.handle(ExecuteOperationCommand(principal, operation.id)) == expected
    assert snapshot(database) == before


@pytest.mark.parametrize("approved", [False, True])
def test_same_operation_concurrently_commits_one_transfer(
    database, principal, clock, monkeypatch, approved
):
    operation = persist_transfer(database, principal, clock, approved)
    outcomes, tools = race(database, principal, clock, [operation, operation], monkeypatch)
    assert outcomes[0] == outcomes[1]
    assert tools.calls == [operation.request.arguments]
    amount = operation.request.arguments.amount.cents
    assert balances(database) == [("acct-alice", 1000000 - amount), ("acct-bob", 1000000 + amount)]
    with closing(connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM operations "
                "WHERE state='SUCCEEDED' AND result_json IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
    assert len(execution_events(database, OperationDispatchedEvent)) == 1
    assert len(execution_events(database, OperationExecutedEvent)) == 1
    with SqliteUnitOfWork(database) as work:
        if approved:
            assert work.approvals.get(operation.id).state == ApprovalState.CONSUMED
    assert_restart_replay(database, principal, clock, operation, outcomes[0])


@pytest.mark.parametrize("approved", [False, True])
def test_competing_transfers_revalidate_funds_under_write_lock(
    database, principal, clock, monkeypatch, approved
):
    amount = 10001 if approved else 10000
    available = amount + 1
    with closing(connect(database)) as connection:
        connection.execute(
            "UPDATE accounts SET balance_cents=? WHERE id='acct-alice'", (available,)
        )
    first = persist_transfer(database, principal, clock, approved)
    second = replace(
        transfer_operation(principal, clock, amount),
        id=OperationId("00000000-0000-4000-8000-000000000002"),
        key=IdempotencyKey("competitor"),
    )
    with SqliteUnitOfWork(database) as work:
        work.operations.add(second)
        work.audit.append(second.requested_event())
        if approved:
            work.approvals.add(Approval(second))
            approval = grant(second, principal, clock)
            work.operations.save_approval_decision(approval.operation)
            work.approvals.save_decision(approval)
            work.audit.append(approval.decided_event())
            second = approval.operation
        work.commit()
    outcomes, tools = race(database, principal, clock, [first, second], monkeypatch)
    assert sum(isinstance(outcome, Forbidden) for outcome in outcomes) == 1
    winner = next(outcome for outcome in outcomes if not isinstance(outcome, Forbidden))
    assert len(tools.calls) == 1
    assert balances(database) == [("acct-alice", 1), ("acct-bob", 1000000 + amount)]
    assert sum(value for _, value in balances(database)) == available + 1000000
    assert [event.operation_id for event in execution_events(database, OperationExecutedEvent)] == [
        winner.operation.id
    ]
    assert len(execution_events(database, OperationDispatchedEvent)) == 1
    for operation in (first, second):
        won = operation.id == winner.operation.id
        with SqliteUnitOfWork(database) as work:
            assert work.operations.get(operation.id).state == (
                OperationState.SUCCEEDED if won else OperationState.READY
            )
            assert work.operations.get_result(operation.id) == (
                operation.request.arguments if won else None
            )
            if approved:
                assert work.approvals.get(operation.id).state == (
                    ApprovalState.CONSUMED if won else ApprovalState.GRANTED
                )
    assert_restart_replay(database, principal, clock, winner.operation, winner)


class SimulatedCrash(BaseException):
    """Interrupt execution without being caught by ordinary application error handlers."""


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize(
    "boundary", ["before_commit", "connection_loss", "confirmed_commit", "uncertain_commit"]
)
def test_commit_boundary_failure_and_restart(database, principal, clock, approved, boundary):
    operation = persist_transfer(database, principal, clock, approved)
    before = snapshot(database)
    tools = CountingTools()
    staged = []
    confirmed = []
    connections = []

    class InterruptedWork(SqliteUnitOfWork):
        def commit(self):
            connections.append(self._connection)
            # The complete proposed transfer exists on this connection only.
            staged.append(
                (self.operations.get(operation.id), self.operations.get_result(operation.id))
            )
            assert staged[-1][0].state == OperationState.SUCCEEDED
            assert staged[-1][1] == operation.request.arguments
            if approved:
                assert self.approvals.get(operation.id).state == ApprovalState.CONSUMED
            if boundary == "before_commit":
                raise SimulatedCrash
            if boundary == "connection_loss":
                # Drop the live transaction without calling UoW.rollback, as on connection loss.
                self._connection.close()
                self._connection = None
                raise SimulatedCrash
            super().commit()
            if boundary == "confirmed_commit":
                confirmed.append(True)
                raise SimulatedCrash  # Durable commit acknowledged; response delivery is lost.
            # SQLite committed, but its acknowledgment is lost to the caller. No blind retry.
            raise StorageUnavailable

    interrupted = handler(database, principal, clock, tools, lambda: InterruptedWork(database))
    if boundary == "uncertain_commit":
        recovered = interrupted.handle(ExecuteOperationCommand(principal, operation.id))
        assert recovered.operation.state == OperationState.SUCCEEDED
    else:
        with pytest.raises(SimulatedCrash):
            interrupted.handle(ExecuteOperationCommand(principal, operation.id))
    assert tools.calls == [operation.request.arguments]
    assert len(staged) == 1
    assert confirmed == ([True] if boundary == "confirmed_commit" else [])
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")

    # Explicit observation after reopening establishes durability; no automatic reconciliation.
    stored = SqliteOperationReadRepository(database).get(operation.id)
    committed = boundary in {"confirmed_commit", "uncertain_commit"}
    if not committed:
        assert_rolled_back(database, before)
        assert stored.operation == operation and stored.result is None
        assert execution_events(database, OperationExecutedEvent) == []
        assert execution_events(database, OperationDispatchedEvent) == []
        if approved:
            with SqliteUnitOfWork(database) as work:
                assert work.approvals.get(operation.id).state == ApprovalState.GRANTED
        # A new explicit command after confirmed rollback can execute the original operation.
        result = handler(database, principal, clock, CountingTools()).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    else:
        assert stored.operation == staged[0][0] and stored.result == staged[0][1]
        result = ExecuteOperationResult(stored.operation, stored.result)
    amount = operation.request.arguments.amount.cents
    assert balances(database) == [("acct-alice", 1000000 - amount), ("acct-bob", 1000000 + amount)]
    assert len(execution_events(database, OperationExecutedEvent)) == 1
    assert len(execution_events(database, OperationDispatchedEvent)) == 1
    if approved:
        with SqliteUnitOfWork(database) as work:
            assert work.approvals.get(operation.id).state == ApprovalState.CONSUMED
            assert work.approvals.get(operation.id).consumed_at == clock.now()
    assert_restart_replay(database, principal, clock, operation, result)
