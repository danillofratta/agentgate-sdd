import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.infrastructure.persistence.database import V2_SCHEMA, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture
from tests.infrastructure.test_transactional_persistence import persist, snapshot

operation = operation_fixture


@pytest.fixture
def approver(principal):
    return replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)


def setup(database, operation, clock):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    return ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock)


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_decision_restart_durability_and_no_execution(
    database, operation, approver, clock, decision
):
    use_case = setup(database, operation, clock)
    with sqlite3.connect(database) as connection:
        balances = connection.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    command = ApproveOperationCommand(approver, operation.id, decision)
    result = use_case.handle(command)
    initialize(database)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.approvals.get(operation.id) == result.approval
        assert reopened.operations.get(operation.id) == result.approval.operation
        assert (
            reopened.operations.find(operation.principal_id, operation.key)
            == result.approval.operation
        )
    stored = SqliteOperationReadRepository(database).get(operation.id)
    assert stored.operation == result.approval.operation
    assert stored.approval.state == (
        ApprovalState.GRANTED if decision == ApprovalDecision.APPROVE else ApprovalState.REJECTED
    )
    assert stored.result is None
    assert stored.operation.policy == operation.policy
    assert stored.operation.state == (
        OperationState.READY if decision == ApprovalDecision.APPROVE else OperationState.REJECTED
    )
    events = SqliteAuditReadRepository(database).list(AuditPage())
    assert [record.event for record in events] == [
        operation.requested_event(),
        result.approval.decided_event(),
    ]
    before = snapshot(database)
    restarted = ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock)
    for later in ApprovalDecision:
        with pytest.raises(InvalidTransition):
            restarted.handle(replace(command, decision=later))
    assert snapshot(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM accounts ORDER BY id").fetchall() == balances


@pytest.mark.parametrize(
    "decisions",
    [
        (ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
        (ApprovalDecision.APPROVE, ApprovalDecision.APPROVE),
        (ApprovalDecision.REJECT, ApprovalDecision.REJECT),
    ],
)
def test_concurrent_decisions_have_exactly_one_winner(
    database, operation, approver, clock, decisions
):
    setup(database, operation, clock)
    barrier = Barrier(2)

    def decide(decision):
        use_case = ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock)
        barrier.wait(timeout=5)
        try:
            return use_case.handle(ApproveOperationCommand(approver, operation.id, decision))
        except InvalidTransition:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, decisions))
    winners = [item for item in outcomes if item is not None]
    assert len(winners) == 1
    with SqliteUnitOfWork(database) as work:
        assert work.approvals.get(operation.id) == winners[0].approval
    assert len(SqliteAuditReadRepository(database).list(AuditPage())) == 2


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_audit_constraint_failure_rolls_back_both_states(
    database, operation, approver, clock, decision
):
    use_case = setup(database, operation, clock)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TRIGGER fail_approval_audit BEFORE INSERT ON audit_events
            WHEN NEW.event_type='APPROVAL_DECIDED'
            BEGIN SELECT RAISE(ABORT, 'SECRET_APPROVAL_SENTINEL'); END""")
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        use_case.handle(ApproveOperationCommand(approver, operation.id, decision))
    assert str(error.value) == ""
    assert snapshot(database) == before
    with SqliteUnitOfWork(database) as work:
        assert work.approvals.get(operation.id) == Approval(operation)
        assert work.operations.get(operation.id) == operation


@pytest.mark.parametrize(
    "column,value",
    [
        ("principal_id", "principal-other"),
        ("fingerprint", "0" * 64),
        ("policy_version", "v2"),
        ("created_at", "2026-10-23T11:59:59+00:00"),
        ("expires_at", "2026-10-24T00:00:00+00:00"),
    ],
)
def test_persisted_binding_mismatch_fails_closed(
    database, operation, approver, clock, column, value
):
    use_case = setup(database, operation, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE approvals SET {column}=?", (value,))
    before = snapshot(database)
    with pytest.raises(StorageUnavailable):
        use_case.handle(ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE))
    assert snapshot(database) == before


def test_stale_repository_snapshots_cannot_replace_decision(database, operation, approver, clock):
    use_case = setup(database, operation, clock)
    stale = Approval(operation).decide(approver, ApprovalDecision.REJECT, clock.now())
    use_case.handle(ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE))
    before = snapshot(database)
    for repository in ("operations", "approvals"):
        with pytest.raises(InvalidTransition):
            with SqliteUnitOfWork(database) as work:
                if repository == "operations":
                    work.operations.save_approval_decision(stale.operation)
                else:
                    work.approvals.save_decision(stale)
                work.commit()
    assert snapshot(database) == before


def test_v2_pending_data_migrates_without_loss(tmp_path, operation, approver, clock):
    database = str(tmp_path / "v2.sqlite3")
    with sqlite3.connect(database) as connection:
        for statement in V2_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=2")
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    initialize(database)
    initialize(database)
    with SqliteUnitOfWork(database) as work:
        assert work.approvals.get(operation.id) == Approval(operation)
    result = ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock).handle(
        ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
    )
    assert result.approval.state == ApprovalState.GRANTED
