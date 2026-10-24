import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.execution_conflict import ExecutionConflict
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.reason import Reason
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.database import connect, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.application.test_secure_transfer_handler import grant, transfer_operation
from tests.infrastructure.test_balance_execution import balances, executor
from tests.infrastructure.test_transactional_persistence import snapshot


def persist_transfer(database, principal, clock, approved):
    operation = transfer_operation(principal, clock, 10001 if approved else 10000)
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.audit.append(operation.requested_event())
        if approved:
            work.approvals.add(Approval(operation))
            approval = grant(operation, principal, clock)
            work.operations.save_approval_decision(approval.operation)
            work.approvals.save_decision(approval)
            work.audit.append(approval.decided_event())
            operation = approval.operation
        work.commit()
    return operation


@pytest.mark.parametrize("approved", [False, True])
def test_atomic_transfer_reopen_terminal_replay_and_idempotent_submission(
    database, principal, clock, approved
):
    operation = persist_transfer(database, principal, clock, approved)
    result = executor(database, clock).handle(ExecuteOperationCommand(principal, operation.id))
    amount = operation.request.arguments.amount.cents
    assert balances(database) == [("acct-alice", 1000000 - amount), ("acct-bob", 1000000 + amount)]
    assert sum(value for _, value in balances(database)) == 2000000
    assert result.operation.policy == operation.policy
    assert result.operation.execution_authorization.decision == Decision.ALLOW
    assert result.operation.execution_authorization.reason == (
        Reason.HUMAN_APPROVED if approved else Reason.PERMITTED
    )
    initialize(database)
    before = snapshot(database)
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == result.operation and stored.result == result.result
    if approved:
        assert stored.approval.state == ApprovalState.CONSUMED
        with SqliteUnitOfWork(database) as work:
            consumed = work.approvals.get(operation.id)
            assert consumed.state == ApprovalState.CONSUMED
            assert consumed.consumed_at == clock.now()
    connection = connect(database)
    try:
        payload = json.loads(connection.execute("SELECT result_json FROM operations").fetchone()[0])
        assert payload == {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        }
        authorization = json.loads(
            connection.execute("SELECT authorization_json FROM operations").fetchone()[0]
        )
        assert authorization == {
            "decision": "ALLOW",
            "reason": "HUMAN_APPROVED" if approved else "PERMITTED",
            "version": "v1",
        }
    finally:
        connection.close()
    handler = executor(database, clock)

    def no_dispatch(*args):
        pytest.fail("terminal replay dispatched a tool")

    handler._harness._tools = SimpleNamespace(dispatch=no_dispatch)
    for _ in range(2):
        assert handler.handle(ExecuteOperationCommand(principal, operation.id)) == result
    request = RequestOperationHandler(
        lambda: SqliteUnitOfWork(database),
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(next_id=lambda: pytest.fail("replay generated identity")),
    ).handle(RequestOperationCommand(principal, operation.key, operation.request))
    assert request.operation == result.operation
    assert snapshot(database) == before
    events = SqliteAuditReadRepository(database).list(AuditPage())
    assert sum(isinstance(record.event, OperationExecutedEvent) for record in events) == 1


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("failure", ["audit", "result", "second_account", "consumption"])
def test_every_write_failure_rolls_back_entire_transfer(
    database, principal, clock, approved, failure
):
    operation = persist_transfer(database, principal, clock, approved)
    before = snapshot(database)

    def broken(*args):
        raise StorageUnavailable

    class FailingWork(SqliteUnitOfWork):
        def __enter__(self):
            super().__enter__()
            if failure == "audit":
                original = self.audit.append

                def append(event):
                    if isinstance(event, OperationExecutedEvent):
                        broken()
                    original(event)

                self.audit = SimpleNamespace(append=append)
            elif failure == "result":
                self.operations.save_execution = broken
            elif failure == "second_account":
                original_save = self.accounts.save

                def save(account):
                    if account.id.value == "acct-bob":
                        broken()
                    original_save(account)

                self.accounts = SimpleNamespace(facts=self.accounts.facts, save=save)
            elif approved:
                self.approvals.save_consumption = broken
            else:
                self.operations.save_execution = broken
            return self

    with pytest.raises((StorageUnavailable, ExecutionUnavailable)) as error:
        executor(database, clock, lambda: FailingWork(database)).handle(
            ExecuteOperationCommand(principal, operation.id)
        )
    assert str(error.value) == ""
    assert snapshot(database) == before
    with SqliteUnitOfWork(database) as work:
        assert work.operations.get(operation.id) == operation
        assert work.operations.get_result(operation.id) is None
        if approved:
            assert work.approvals.get(operation.id).state == ApprovalState.GRANTED


@pytest.mark.parametrize("change", ["tools", "source_accounts", "funds", "destination", "pending"])
def test_current_sqlite_facts_deny_without_approval_consumption(database, principal, clock, change):
    if change == "pending":
        operation = transfer_operation(principal, clock, 10001)
        with SqliteUnitOfWork(database) as work:
            work.operations.add(operation)
            work.approvals.add(Approval(operation))
            work.audit.append(operation.requested_event())
            work.commit()
    else:
        operation = persist_transfer(database, principal, clock, True)
    if change in {"funds", "destination"}:
        connection = connect(database)
        try:
            if change == "funds":
                connection.execute("UPDATE accounts SET balance_cents=10000 WHERE id='acct-alice'")
            else:
                connection.execute("DELETE FROM accounts WHERE id='acct-bob'")
        finally:
            connection.close()
    before = snapshot(database)
    handler = executor(database, clock)
    if change in {"tools", "source_accounts"}:
        handler._principals = SimpleNamespace(
            get_principal=lambda principal_id: replace(principal, **{change: frozenset()})
        )
    handler._harness._tools = SimpleNamespace(dispatch=lambda *args: pytest.fail("denied dispatch"))
    with pytest.raises(ExecutionConflict if change == "pending" else Forbidden):
        handler.handle(ExecuteOperationCommand(principal, operation.id))
    assert snapshot(database) == before
    with SqliteUnitOfWork(database) as work:
        assert work.approvals.get(operation.id).state == (
            ApprovalState.PENDING if change == "pending" else ApprovalState.GRANTED
        )
