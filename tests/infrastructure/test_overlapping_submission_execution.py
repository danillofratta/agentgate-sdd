"""A controlled overlapping submit/execute pipeline, without scheduler races."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from tests.domain.test_request_values import transfer
from tests.infrastructure.test_balance_execution import balances
from tests.infrastructure.test_concurrent_execution_recovery import (
    CountingTools,
    handler,
    snapshot,
)


def test_submission_overlaps_execution_and_both_callers_replay_one_transfer(
    database, principal, clock
):
    dispatching = Event()
    submitting = Event()
    committed = Event()
    tools = CountingTools()
    connections = []

    def work():
        unit = SqliteUnitOfWork(database)
        connections.append(unit)
        return unit

    def overlapping_work():
        # The second handle() is active while the first execution owns its UoW.
        # Gate BEFORE opening SQLite: no sleep or assumption about 50 ms locks.
        assert dispatching.wait(10)
        submitting.set()
        assert committed.wait(10)
        return work()

    class PausedTools:
        def dispatch(self, tool, arguments, accounts):
            dispatching.set()
            assert submitting.wait(10)
            return tools.dispatch(tool, arguments, accounts)

    def requester(factory):
        return RequestOperationHandler(
            factory, EvaluatePolicyHandler(), clock, UuidOperationIdGenerator()
        )

    command = RequestOperationCommand(principal, IdempotencyKey("overlap"), transfer(1))

    def first_pipeline():
        requested = requester(work).handle(command)
        try:
            executed = handler(database, principal, clock, PausedTools(), work).handle(
                ExecuteOperationCommand(principal, requested.operation.id)
            )
            return requested, executed
        finally:
            committed.set()

    def second_pipeline():
        assert dispatching.wait(10)
        requested = requester(overlapping_work).handle(command)
        before = snapshot(database)
        executed = handler(database, principal, clock, tools, work).handle(
            ExecuteOperationCommand(principal, requested.operation.id)
        )
        assert snapshot(database) == before
        return requested, executed

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_pipeline)
        second = pool.submit(second_pipeline)
        created, executed = first.result(timeout=15)
        replayed, replay_execution = second.result(timeout=15)

    assert created.created and not replayed.created
    assert created.operation.id == replayed.operation.id
    assert executed == replay_execution
    assert replayed.result == executed.result
    assert len(tools.calls) == 1
    assert balances(database) == [("acct-alice", 999999), ("acct-bob", 1000001)]
    assert len(connections) == len({id(unit) for unit in connections})
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone() == (0,)
        rows = connection.execute(
            "SELECT event_type, COUNT(*) FROM audit_events GROUP BY event_type"
        ).fetchall()
        assert dict(rows) == {
            "OPERATION_REQUESTED": 1,
            "OPERATION_ATTEMPTED": 1,
            "OPERATION_DISPATCHED": 1,
            "OPERATION_EXECUTED": 1,
        }
