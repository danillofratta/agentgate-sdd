import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.infrastructure.gateways.local_tool_registry_gateway import LocalToolRegistryGateway
from agentgate.infrastructure.persistence.database import connect, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from agentgate.infrastructure.tools.get_balance_adapter import GetBalanceAdapter
from agentgate.infrastructure.tools.simulate_transfer_adapter import SimulateTransferAdapter
from tests.application.test_execute_operation_handler import balance_operation
from tests.domain.test_request_values import transfer


def registry():
    return LocalToolRegistryGateway(GetBalanceAdapter(), SimulateTransferAdapter())


def seed_operation(database, operation):
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.audit.append(operation.requested_event())
        work.commit()


def executor(database, clock, factory=None):
    return ExecuteOperationHandler(
        factory or (lambda: SqliteUnitOfWork(database)),
        registry(),
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(sleep=lambda seconds: pytest.fail("unexpected sleep")),
    )


def balances(database):
    connection = connect(database)
    try:
        return [tuple(row) for row in connection.execute("SELECT * FROM accounts ORDER BY id")]
    finally:
        connection.close()


def test_offline_balance_execution_durable_after_reopen(database, principal, clock):
    operation = balance_operation(principal, clock)
    seed_operation(database, operation)
    before = balances(database)
    result = executor(database, clock).handle(ExecuteOperationCommand(principal, operation.id))
    assert result.result == BalanceResult(AccountId("acct-alice"), 1000000, "USD")
    assert result.operation.state == OperationState.SUCCEEDED
    assert balances(database) == before

    initialize(database)
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == result.operation
    assert stored.result == result.result
    connection = connect(database)
    try:
        raw = connection.execute("SELECT result_json FROM operations").fetchone()[0]
        assert json.loads(raw) == {
            "account_id": "acct-alice",
            "balance_cents": 1000000,
            "currency": "USD",
        }
    finally:
        connection.close()
    events = SqliteAuditReadRepository(database).list(AuditPage())
    assert len(events) == 3
    assert isinstance(events[1].event, OperationDispatchedEvent)
    assert isinstance(events[2].event, OperationExecutedEvent)
    assert all(record.event.operation_id == operation.id for record in events)
    assert (
        events[1].event.fingerprint == events[2].event.fingerprint == operation.request.fingerprint
    )
    # Terminal replay is task 5.2; this increment refuses to redispatch.
    with pytest.raises(InvalidTransition):
        executor(database, clock).handle(ExecuteOperationCommand(principal, operation.id))
    assert balances(database) == before
    assert SqliteAuditReadRepository(database).list(AuditPage()) == events


@pytest.mark.parametrize("failure_event", [OperationDispatchedEvent, OperationExecutedEvent])
def test_execution_evidence_failure_rolls_back(database, principal, clock, failure_event):
    operation = balance_operation(principal, clock)
    seed_operation(database, operation)
    before = balances(database)

    class BrokenAuditWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            original = self.audit

            def append(event):
                if isinstance(event, failure_event):
                    raise StorageUnavailable
                original.append(event)

            self.audit = SimpleNamespace(append=append)
            return self

    with pytest.raises(StorageUnavailable):
        executor(database, clock, lambda: BrokenAuditWork(database)).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == operation and stored.result is None
    assert balances(database) == before
    assert len(SqliteAuditReadRepository(database).list(AuditPage())) == 1


def test_transfer_placeholder_preserves_database(database, principal, clock):
    operation = replace(balance_operation(principal, clock), request=transfer(1))
    seed_operation(database, operation)
    before = balances(database)
    with pytest.raises(ExecutionUnavailable):
        executor(database, clock).handle(ExecuteOperationCommand(principal, operation.id))
    assert balances(database) == before
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == operation and stored.result is None
    assert len(SqliteAuditReadRepository(database).list(AuditPage())) == 1


def test_adapters_have_no_transaction_or_io_capability(principal, clock):
    assert not vars(GetBalanceAdapter()) and not vars(SimulateTransferAdapter())
    assert not hasattr(GetBalanceAdapter(), "commit")
    assert not hasattr(SimulateTransferAdapter(), "commit")
    with pytest.raises(ExecutionUnavailable):
        SimulateTransferAdapter().run(transfer(1).arguments, ())


@pytest.mark.parametrize("tool", ["unknown", "../get_balance", "simulate_transfer; shell"])
def test_fixed_registry_rejects_unknown_tool_without_adapter_call(tool):
    def forbidden_call(*args):
        pytest.fail("unknown tool reached an adapter")

    local = LocalToolRegistryGateway(
        SimpleNamespace(run=forbidden_call), SimpleNamespace(run=forbidden_call)
    )
    with pytest.raises(ExecutionUnavailable):
        local.dispatch(tool, transfer(1).arguments, ())


def test_existing_audit_http_adapter_can_render_execution_evidence(database, principal, clock):
    from agentgate.features.list_audit.endpoint import list_audit
    from agentgate.features.list_audit.handler import ListAuditHandler

    operation = balance_operation(principal, clock)
    seed_operation(database, operation)
    executor(database, clock).handle(ExecuteOperationCommand(principal, operation.id))
    from agentgate.domain.value_objects.role import Role

    response = list_audit(
        replace(principal, role=Role.APPROVER),
        ListAuditHandler(SqliteAuditReadRepository(database)),
        0,
        50,
    )
    assert [event.event_type for event in response.events] == [
        "OPERATION_REQUESTED",
        "OPERATION_DISPATCHED",
        "OPERATION_EXECUTED",
    ]
    assert response.events[-1].decision == "SUCCEEDED"
    assert response.events[-1].reason == "EXECUTION_SUCCEEDED"
