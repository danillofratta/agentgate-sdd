from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.domain.entities.approval import Approval
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from tests.application.test_request_handler import FakeUnitOfWork, handler
from tests.domain.test_request_values import transfer
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture

operation = operation_fixture


@pytest.fixture
def approver(principal):
    return replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)


def approval_work(operation):
    work = FakeUnitOfWork()
    work.saved[operation.principal_id, operation.key] = operation
    work.pending.append(Approval(operation))
    work.operations.get = lambda _: next(iter(work.saved.values()), None)
    work.operations.save_approval_decision = lambda item: work.saved.update(
        {(item.principal_id, item.key): item}
    )
    work.approvals.get = lambda _: next(iter(work.pending), None)
    work.approvals.save_decision = lambda item: work.pending.__setitem__(0, item)
    return work


@pytest.mark.parametrize("decision", list(ApprovalDecision))
def test_fake_ports_decide_without_accounts_or_tools(operation, approver, clock, decision):
    work = approval_work(operation)
    # No tool port exists, and even reading account facts would fail this test.
    work.accounts = SimpleNamespace()
    result = ApproveOperationHandler(lambda: work, clock).handle(
        ApproveOperationCommand(approver, operation.id, decision)
    )
    assert result.approval.operation.state == (
        OperationState.READY if decision == ApprovalDecision.APPROVE else OperationState.REJECTED
    )
    assert result.approval.operation.policy == operation.policy
    assert result.approval.decided_at == clock.now()
    assert work.commits == 1
    assert work.events == [result.approval.decided_event()]


@pytest.mark.parametrize("self_approver", [False, True])
def test_direct_handler_cannot_self_approve(operation, principal, clock, self_approver):
    work = approval_work(operation)
    caller = replace(principal, role=Role.APPROVER) if self_approver else principal
    with pytest.raises(Forbidden):
        ApproveOperationHandler(lambda: work, clock).handle(
            ApproveOperationCommand(caller, operation.id, ApprovalDecision.APPROVE)
        )
    assert work.pending == [Approval(operation)]
    assert not work.events and work.commits == 0


@pytest.mark.parametrize("field", ["principal", "operation_id", "decision"])
def test_untyped_command_rejected(operation, approver, field):
    command = ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
    with pytest.raises(InvariantViolation):
        replace(command, **{field: {"role": "APPROVER"}})


@pytest.mark.parametrize("changed", ["principal", "request", "policy", "id"])
def test_handler_checks_exact_binding_with_fake_repository(operation, approver, clock, changed):
    work = approval_work(operation)
    changes = {
        "principal": {"principal_id": PrincipalId("principal-other")},
        "request": {"request": transfer(20000)},
        "policy": {"policy": replace(operation.policy, version=PolicyVersion("v2"))},
        "id": {"id": replace(operation.id, value="00000000-0000-4000-8000-000000000002")},
    }
    work.pending[:] = [Approval(replace(operation, **changes[changed]))]
    with pytest.raises(ApprovalBindingMismatch):
        ApproveOperationHandler(lambda: work, clock).handle(
            ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
        )
    assert not work.events and work.commits == 0


@pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.DENY])
def test_nonpending_operation_cannot_be_decided(operation, approver, clock, decision):
    item = replace(
        operation,
        policy=PolicyDecision(
            decision,
            Reason.PERMITTED if decision == Decision.ALLOW else Reason.LIMIT_EXCEEDED,
            operation.policy.version,
        ),
    )
    work = approval_work(operation)
    work.operations.get = lambda _: item
    with pytest.raises(InvalidTransition):
        ApproveOperationHandler(lambda: work, clock).handle(
            ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
        )
    assert not work.events and work.commits == 0


def test_missing_operation_and_missing_approval_fail_closed(operation, approver, clock):
    work = approval_work(operation)
    use_case = ApproveOperationHandler(lambda: work, clock)
    command = ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
    work.operations.get = lambda _: None
    with pytest.raises(NotFound):
        use_case.handle(command)
    work.operations.get = lambda _: operation
    work.pending.clear()
    with pytest.raises(ApprovalBindingMismatch):
        use_case.handle(command)
    assert not work.events and work.commits == 0


def test_audit_failure_rolls_back_fake_ports(operation, approver, clock):
    work = approval_work(operation)

    def fail(_):
        raise RuntimeError("audit failure")

    work.audit.append = fail
    with pytest.raises(RuntimeError):
        ApproveOperationHandler(lambda: work, clock).handle(
            ApproveOperationCommand(approver, operation.id, ApprovalDecision.REJECT)
        )
    assert work.saved[operation.principal_id, operation.key] == operation
    assert work.pending == [Approval(operation)]
    assert not work.events and work.commits == 0


def test_existing_submission_still_atomically_creates_pending(principal, clock):
    from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
    from agentgate.features.request_operation.command import RequestOperationCommand

    work = FakeUnitOfWork()
    result = handler(work, clock).handle(
        RequestOperationCommand(principal, IdempotencyKey("pending"), transfer())
    )
    assert work.pending == [Approval(result.operation)]
    assert work.commits == 1 and len(work.events) == 1
