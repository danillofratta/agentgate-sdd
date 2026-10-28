"""Executable task 4.3 walkthrough using existing commands, queries and SQLite UoW."""

import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.approval import Approval
from agentgate.domain.enums.approval_decision import ApprovalDecision
from agentgate.domain.enums.approval_state import ApprovalState
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.role import Role
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.expire_approval.command import ExpireApprovalCommand
from agentgate.features.expire_approval.handler import ExpireApprovalHandler
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.get_operation.query import GetOperationQuery
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.list_audit.query import ListAuditQuery
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.domain.test_request_values import transfer
from tests.infrastructure.test_transactional_persistence import snapshot


def balances(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT * FROM accounts ORDER BY id").fetchall()


def audit_rows(database):
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM audit_events ORDER BY id")]


@pytest.fixture
def walkthrough(database, principal, clock):
    """Each case gets its own seeded file and fake clock; creation uses the real handler."""
    before = balances(database)

    def factory():
        return SqliteUnitOfWork(database)

    request = RequestOperationHandler(
        factory,
        EvaluatePolicyHandler(),
        clock,
        SimpleNamespace(next_id=lambda: "00000000-0000-4000-8000-000000000001"),
    )
    command = RequestOperationCommand(principal, IdempotencyKey("walkthrough"), transfer())
    operation = request.handle(command).operation
    approver = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
    context = SimpleNamespace(
        operation=operation,
        approver=approver,
        request=request,
        command=command,
        approve=ApproveOperationHandler(factory, clock),
        get=GetOperationHandler(SqliteOperationReadRepository(database)),
        audit=ListAuditHandler(SqliteAuditReadRepository(database)),
    )
    assert operation.state == OperationState.PENDING_APPROVAL
    assert operation.policy.decision == Decision.REQUIRE_APPROVAL
    assert operation.policy.reason == Reason.APPROVAL_REQUIRED
    assert context.get.handle(GetOperationQuery(principal, operation.id)).approval.state == (
        ApprovalState.PENDING
    )
    assert_request_evidence(database, operation)
    yield context
    # Covers request, decisions, inspection, failed decisions and rollback paths.
    assert balances(database) == before
    assert context.get.handle(GetOperationQuery(approver, operation.id)).result is None


def assert_request_evidence(database, operation):
    assert audit_rows(database) == [
        {
            "id": 1,
            "event_type": "OPERATION_REQUESTED",
            "operation_id": operation.id.value,
            "principal_id": operation.principal_id.value,
            "tool": "simulate_transfer",
            "decision": "REQUIRE_APPROVAL",
            "reason": "APPROVAL_REQUIRED",
            "policy_version": "v1",
            "occurred_at": operation.created_at.isoformat(),
            "approver_id": None,
            "fingerprint": None,
            "attempt": None,
        }
    ]


@pytest.mark.parametrize(
    "decision,approval_state,operation_state,reason",
    [
        (ApprovalDecision.APPROVE, ApprovalState.GRANTED, OperationState.READY, "HUMAN_APPROVED"),
        (
            ApprovalDecision.REJECT,
            ApprovalState.REJECTED,
            OperationState.REJECTED,
            "HUMAN_REJECTED",
        ),
    ],
)
def test_pending_decision_reopen_and_correlated_sanitized_evidence(
    database, principal, clock, walkthrough, decision, approval_state, operation_state, reason
):
    demo = walkthrough
    original = demo.operation
    request_evidence = audit_rows(database)[0]
    clock.value += timedelta(seconds=30)
    decided = demo.approve.handle(
        ApproveOperationCommand(demo.approver, original.id, decision)
    ).approval
    assert decided.state == approval_state
    assert decided.operation.state == operation_state
    assert decided.operation.policy == original.policy
    assert decided.operation.request == original.request
    assert decided.operation.principal_id == original.principal_id
    assert decided.consumed_at is None
    expected = [
        request_evidence,
        {
            "id": 2,
            "event_type": "APPROVAL_DECIDED",
            "operation_id": original.id.value,
            "principal_id": principal.id.value,
            "tool": "simulate_transfer",
            "decision": decision.value,
            "reason": reason,
            "policy_version": "v1",
            "occurred_at": clock.now().isoformat(),
            "approver_id": demo.approver.id.value,
            "fingerprint": original.request.fingerprint.value,
            "attempt": None,
        },
    ]
    # Exact field allowlist excludes arguments, amounts, credentials and raw input.
    assert audit_rows(database) == expected
    before = snapshot(database)
    initialize(database, seed=False)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.approvals.get(original.id) == decided
        assert reopened.operations.get(original.id) == decided.operation
    reader = GetOperationHandler(SqliteOperationReadRepository(database))
    audit = ListAuditHandler(SqliteAuditReadRepository(database))
    for _ in range(3):
        for caller in (principal, demo.approver):
            view = reader.handle(GetOperationQuery(caller, original.id))
            assert view.operation == decided.operation
            assert view.approval.state == approval_state
            assert view.approval.expires_at == original.created_at + timedelta(seconds=300)
            assert view.result is None
        records = audit.handle(ListAuditQuery(demo.approver)).events
        assert [record.id for record in records] == [1, 2]
        assert [record.event for record in records] == [
            original.requested_event(),
            decided.decided_event(),
        ]
    replay = demo.request.handle(demo.command)
    assert not replay.created and replay.operation == decided.operation
    restarted = ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock)
    for duplicate in ApprovalDecision:
        with pytest.raises(InvalidTransition):
            restarted.handle(ApproveOperationCommand(demo.approver, original.id, duplicate))
    assert audit_rows(database) == expected
    assert snapshot(database) == before


def test_exact_300_second_expiry_requires_command_and_queries_preserve_state(
    database, principal, clock, walkthrough
):
    demo = walkthrough
    pending = Approval(demo.operation)
    before = snapshot(database)
    clock.value = pending.expires_at - timedelta(microseconds=1)
    assert not pending.deadline.expired(clock.now())
    with pytest.raises(InvalidTransition):
        pending.expire(clock.now())
    clock.value += timedelta(microseconds=1)
    assert clock.now() == demo.operation.created_at + timedelta(seconds=300)
    expired = pending.expire(clock.now())
    assert expired.state == ApprovalState.EXPIRED
    assert expired.operation.state == OperationState.EXPIRED
    assert expired.operation.policy == demo.operation.policy
    assert expired.operation.request == demo.operation.request
    assert pending.state == ApprovalState.PENDING
    for decision in ApprovalDecision:
        with pytest.raises(InvalidTransition):
            demo.approve.handle(ApproveOperationCommand(demo.approver, demo.operation.id, decision))
    # Query handlers have no clock: they expose persisted metadata, not derived expiry.
    for elapsed in (300, 301, 600):
        clock.value = demo.operation.created_at + timedelta(seconds=elapsed)
        for caller in (principal, demo.approver):
            view = demo.get.handle(GetOperationQuery(caller, demo.operation.id))
            assert view.operation.state == OperationState.PENDING_APPROVAL
            assert view.approval.state == ApprovalState.PENDING
            assert view.approval.expires_at == pending.expires_at
        records = demo.audit.handle(ListAuditQuery(demo.approver)).events
        assert [record.event for record in records] == [demo.operation.requested_event()]
    initialize(database, seed=False)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.approvals.get(demo.operation.id) == pending
    # No expiry evidence is invented before the explicit internal command.
    assert_request_evidence(database, demo.operation)
    assert snapshot(database) == before
    clock.value = pending.expires_at
    result = ExpireApprovalHandler(lambda: SqliteUnitOfWork(database), clock).handle(
        ExpireApprovalCommand(demo.operation.id)
    )
    assert result == expired
    records = demo.audit.handle(ListAuditQuery(demo.approver)).events
    assert [record.event for record in records] == [
        demo.operation.requested_event(),
        expired.expired_event(clock.now()),
    ]
    initialize(database, seed=False)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.approvals.get(demo.operation.id) == expired
    before = snapshot(database)
    for caller in (principal, demo.approver):
        view = demo.get.handle(GetOperationQuery(caller, demo.operation.id))
        assert view.operation.state == OperationState.EXPIRED
        assert view.approval.state == ApprovalState.EXPIRED
    assert snapshot(database) == before


def test_unauthorized_access_and_changed_request_cannot_rebind_approval(
    database, principal, clock, walkthrough
):
    demo = walkthrough
    before = snapshot(database)
    other = replace(principal, id=PrincipalId("principal-other"))
    for caller in (principal, other, replace(principal, role=Role.APPROVER)):
        with pytest.raises(Forbidden):
            demo.approve.handle(
                ApproveOperationCommand(caller, demo.operation.id, ApprovalDecision.APPROVE)
            )
    with pytest.raises(NotFound):
        demo.get.handle(GetOperationQuery(other, demo.operation.id))
    with pytest.raises(Forbidden):
        demo.audit.handle(ListAuditQuery(principal))
    with pytest.raises(IdempotencyConflict):
        demo.request.handle(replace(demo.command, request=transfer(20000)))
    with pytest.raises(FrozenInstanceError):
        demo.operation.policy = replace(demo.operation.policy, version=PolicyVersion("v2"))
    assert snapshot(database) == before
    granted = demo.approve.handle(
        ApproveOperationCommand(demo.approver, demo.operation.id, ApprovalDecision.APPROVE)
    ).approval
    before = snapshot(database)
    # Pure domain binding checks exercise bypass of HTTP without invoking execution.
    for operation, version, caller in (
        (replace(granted.operation, request=transfer(20000)), PolicyVersion("v1"), principal),
        (granted.operation, PolicyVersion("v2"), principal),
        (granted.operation, PolicyVersion("v1"), other),
    ):
        with pytest.raises(ApprovalBindingMismatch):
            granted.consume(operation, version, clock.now(), principal=caller)
    assert snapshot(database) == before


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_walkthrough_audit_failure_rolls_back_then_reopens_pending(
    database, principal, clock, walkthrough, decision, caplog
):
    demo = walkthrough
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER fail_walkthrough_audit
            BEFORE INSERT ON audit_events WHEN NEW.event_type='APPROVAL_DECIDED'
            BEGIN SELECT RAISE(ABORT, 'PRIVATE_WALKTHROUGH_SENTINEL'); END""")
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        demo.approve.handle(ApproveOperationCommand(demo.approver, demo.operation.id, decision))
    assert str(error.value) == ""
    assert "PRIVATE_WALKTHROUGH_SENTINEL" not in caplog.text
    assert "PRIVATE_WALKTHROUGH_SENTINEL" not in repr(audit_rows(database))
    assert snapshot(database) == before
    # Remove only the test fault before schema validation, which rejects unknown triggers.
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TRIGGER fail_walkthrough_audit")
    initialize(database, seed=False)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.operations.get(demo.operation.id) == demo.operation
        assert reopened.approvals.get(demo.operation.id) == Approval(demo.operation)
    assert demo.get.handle(GetOperationQuery(principal, demo.operation.id)).approval.state == (
        ApprovalState.PENDING
    )
    assert_request_evidence(database, demo.operation)
