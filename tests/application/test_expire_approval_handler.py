from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.features.expire_approval.command import ExpireApprovalCommand
from agentgate.features.expire_approval.handler import ExpireApprovalHandler
from tests.application.test_approve_operation_handler import approval_work
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture

operation = operation_fixture


@pytest.mark.parametrize("granted", [False, True])
def test_expiry_with_fake_ports_never_reads_accounts_or_dispatches(
    operation, principal, clock, granted
):
    work = approval_work(operation)
    if granted:
        approver = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
        approval = work.pending[0].decide(approver, ApprovalDecision.APPROVE, clock.now())
        work.pending[0] = approval
        work.saved[operation.principal_id, operation.key] = approval.operation
    work.operations.save_approval_expiry = work.operations.save_approval_decision
    work.approvals.save_expiry = work.approvals.save_decision
    work.accounts = SimpleNamespace()  # No readable accounts and no tool collaborator.
    clock.value = operation.created_at + timedelta(seconds=300)
    handler = ExpireApprovalHandler(lambda: work, clock)
    command = ExpireApprovalCommand(operation.id)
    result = handler.handle(command)
    assert result.state == ApprovalState.EXPIRED
    assert work.events == [result.expired_event(clock.now())]
    assert work.commits == 1
    assert handler.handle(command) == result
    assert work.commits == 1 and len(work.events) == 1


def test_expiry_rejects_mismatched_snapshot_before_writes(operation, clock):
    work = approval_work(operation)
    work.operations.get = lambda _: replace(operation, principal_id=PrincipalId("principal-other"))
    clock.value += timedelta(seconds=300)
    with pytest.raises(ApprovalBindingMismatch):
        ExpireApprovalHandler(lambda: work, clock).handle(ExpireApprovalCommand(operation.id))
    assert not work.events and work.commits == 0


def test_internal_command_rejects_untyped_identifier():
    with pytest.raises(InvariantViolation):
        ExpireApprovalCommand("untrusted-raw-input")
