"""Internal command expiry: real repositories/UoW, isolated files, injected time."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from threading import Barrier

import pytest

from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.enums.approval_decision import ApprovalDecision
from agentgate.domain.enums.approval_state import ApprovalState
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.expire_approval.command import ExpireApprovalCommand
from agentgate.features.expire_approval.handler import ExpireApprovalHandler
from agentgate.features.get_operation.query import GetOperationQuery
from agentgate.features.list_audit.query import ListAuditQuery
from agentgate.infrastructure.persistence.database import V3_SCHEMA, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from tests.infrastructure.test_human_approval_walkthrough import audit_rows, balances
from tests.infrastructure.test_human_approval_walkthrough import walkthrough as walkthrough_fixture
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture
from tests.infrastructure.test_transactional_persistence import persist, snapshot

walkthrough = walkthrough_fixture
operation = operation_fixture


def current_approval(database, operation):
    with SqliteUnitOfWork(database) as work:
        return work.approvals.get(operation.id)


def prepare(database, clock, demo, granted):
    if granted:
        # A late grant must not extend the original creation + 300-second deadline.
        clock.value = demo.operation.created_at + timedelta(seconds=299)
        demo.approve.handle(
            ApproveOperationCommand(demo.approver, demo.operation.id, ApprovalDecision.APPROVE)
        )
    return ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock)


@pytest.mark.parametrize("granted", [False, True])
@pytest.mark.parametrize("microseconds", [-1, 0, 1])
def test_expiry_boundary_reopen_binding_audit_and_read_only_queries(
    database, clock, principal, walkthrough, granted, microseconds
):
    demo = walkthrough
    handler = prepare(database, clock, demo, granted)
    approval = current_approval(database, demo.operation)
    before_balances = balances(database)
    clock.value = approval.expires_at + timedelta(microseconds=microseconds)
    before = snapshot(database)
    # Reaching the deadline alone and inspecting data must not persist expiry.
    for caller in (principal, demo.approver):
        view = demo.get.handle(GetOperationQuery(caller, demo.operation.id))
        assert view.approval.state == approval.state
    demo.audit.handle(ListAuditQuery(demo.approver))
    assert snapshot(database) == before
    command = ExpireApprovalCommand(demo.operation.id)
    if microseconds < 0:
        with pytest.raises(InvalidTransition):
            handler.handle(command)
        assert snapshot(database) == before
        return
    expired = handler.handle(command)
    assert expired == approval.expire(clock.now())
    assert expired.state == ApprovalState.EXPIRED
    assert expired.operation.state == OperationState.EXPIRED
    assert expired.operation == approval.operation.transition(OperationState.EXPIRED)
    assert expired.expires_at == demo.operation.created_at + timedelta(seconds=300)
    assert expired.decision == approval.decision
    assert expired.approver_id == approval.approver_id
    assert expired.decided_at == approval.decided_at
    assert expired.consumed_at is None
    expected_audit = audit_rows(database)
    assert expected_audit[-1] == {
        "id": 3 if granted else 2,
        "event_type": "APPROVAL_EXPIRED",
        "operation_id": demo.operation.id.value,
        "principal_id": principal.id.value,
        "tool": "simulate_transfer",
        "decision": "EXPIRED",
        "reason": "APPROVAL_EXPIRED",
        "policy_version": "v1",
        "occurred_at": clock.now().isoformat(),
        "approver_id": None,
        "fingerprint": demo.operation.request.fingerprint.value,
        "attempt": None,
    }
    records = demo.audit.handle(ListAuditQuery(demo.approver)).events
    assert records[-1].event == expired.expired_event(clock.now())
    after = snapshot(database)
    initialize(database, seed=False)
    restarted = ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock)
    for _ in range(3):
        assert restarted.handle(command) == expired
        assert current_approval(database, demo.operation) == expired
        for caller in (principal, demo.approver):
            view = demo.get.handle(GetOperationQuery(caller, demo.operation.id))
            assert view.operation == expired.operation
            assert view.approval.state == ApprovalState.EXPIRED
            assert view.result is None
        assert demo.audit.handle(ListAuditQuery(demo.approver)).events == records
    replay = demo.request.handle(demo.command)
    assert not replay.created and replay.operation == expired.operation
    assert snapshot(database) == after
    assert audit_rows(database) == expected_audit
    assert balances(database) == before_balances


@pytest.mark.parametrize("granted", [False, True])
def test_failed_expiry_audit_rolls_back_both_states_and_can_retry(
    database, clock, walkthrough, granted, caplog
):
    demo = walkthrough
    handler = prepare(database, clock, demo, granted)
    approval = current_approval(database, demo.operation)
    clock.value = approval.expires_at
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER fail_expiry_audit BEFORE INSERT ON audit_events
            WHEN NEW.event_type='APPROVAL_EXPIRED'
            BEGIN SELECT RAISE(ABORT, 'PRIVATE_EXPIRY_SENTINEL'); END""")
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        handler.handle(ExpireApprovalCommand(demo.operation.id))
    assert str(error.value) == ""
    assert "PRIVATE_EXPIRY_SENTINEL" not in caplog.text
    assert "PRIVATE_EXPIRY_SENTINEL" not in repr(audit_rows(database))
    assert snapshot(database) == before
    assert current_approval(database, demo.operation) == approval
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TRIGGER fail_expiry_audit")
    initialize(database, seed=False)
    assert current_approval(database, demo.operation) == approval
    handler.handle(ExpireApprovalCommand(demo.operation.id))
    assert [row["event_type"] for row in audit_rows(database)].count("APPROVAL_EXPIRED") == 1


@pytest.mark.parametrize("granted", [False, True])
def test_concurrent_expiry_and_later_replay_write_one_event(database, clock, walkthrough, granted):
    demo = walkthrough
    prepare(database, clock, demo, granted)
    clock.value = demo.operation.created_at + timedelta(seconds=300)
    barrier = Barrier(2)

    def expire(_):
        handler = ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock)
        barrier.wait(timeout=5)
        return handler.handle(ExpireApprovalCommand(demo.operation.id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(expire, range(2)))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0].state == ApprovalState.EXPIRED
    assert [row["event_type"] for row in audit_rows(database)].count("APPROVAL_EXPIRED") == 1
    before = snapshot(database)
    clock.value += timedelta(seconds=300)
    initialize(database, seed=False)
    ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock).handle(
        ExpireApprovalCommand(demo.operation.id)
    )
    assert snapshot(database) == before


@pytest.mark.parametrize("state", ["REJECTED", "DENIED", "SUCCEEDED", "FAILED", "TIMED_OUT"])
def test_expiry_never_changes_terminal_operation(database, clock, operation, state):
    # Stored terminal fixtures do not implement execution. Handler must refuse them
    # before attempting any approval transition or writing audit.
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE operations SET state=?", (state,))
    clock.value = operation.created_at + timedelta(seconds=300)
    before = snapshot(database)
    with pytest.raises(InvalidTransition):
        ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock).handle(
            ExpireApprovalCommand(operation.id)
        )
    assert snapshot(database) == before


@pytest.mark.parametrize("decision", [None, ApprovalDecision.APPROVE, ApprovalDecision.REJECT])
def test_v3_migration_preserves_pending_and_decided_data(tmp_path, clock, walkthrough, decision):
    demo = walkthrough
    database = str(tmp_path / "previous.sqlite3")
    with closing(sqlite3.connect(database)) as connection, connection:
        for statement in V3_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=3")
    approval = Approval(demo.operation)
    if decision is not None:
        approval = approval.decide(demo.approver, decision, clock.now())
    with SqliteUnitOfWork(database) as work:
        work.operations.add(demo.operation)
        work.approvals.add(Approval(demo.operation))
        work.audit.append(demo.operation.requested_event())
        if decision is not None:
            work.operations.save_approval_decision(approval.operation)
            work.approvals.save_decision(approval)
            work.audit.append(approval.decided_event())
        work.commit()
    before_audit = audit_rows(database)
    initialize(database, seed=False)
    assert current_approval(database, demo.operation) == approval
    assert audit_rows(database) == [dict(row, attempt=None) for row in before_audit]
    before = snapshot(database)
    initialize(database, seed=False)
    assert snapshot(database) == before
    clock.value = approval.expires_at
    handler = ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock)
    if decision == ApprovalDecision.REJECT:
        with pytest.raises(InvalidTransition):
            handler.handle(ExpireApprovalCommand(demo.operation.id))
    else:
        assert (
            handler.handle(ExpireApprovalCommand(demo.operation.id)).state == ApprovalState.EXPIRED
        )


def test_missing_operation_is_not_created_by_expiry(database, clock, walkthrough):
    before = snapshot(database)
    with pytest.raises(NotFound):
        ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock).handle(
            ExpireApprovalCommand(OperationId("00000000-0000-4000-8000-000000000002"))
        )
    assert snapshot(database) == before
