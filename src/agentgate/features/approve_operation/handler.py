from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.role import Role
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.result import ApproveOperationResult


class ApproveOperationHandler:
    def __init__(self, unit_of_work: RequestUnitOfWorkFactory, clock: ClockGateway) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def handle(self, command: ApproveOperationCommand) -> ApproveOperationResult:
        if command.principal.role != Role.APPROVER:
            raise Forbidden
        with self._unit_of_work() as work:
            operation = work.operations.get(command.operation_id)
            if operation is None:
                raise NotFound
            if operation.id != command.operation_id:
                raise ApprovalBindingMismatch("APPROVAL_BINDING_MISMATCH")
            if command.principal.id == operation.principal_id:
                raise Forbidden
            if (
                operation.state != OperationState.PENDING_APPROVAL
                or operation.policy.decision != Decision.REQUIRE_APPROVAL
            ):
                raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
            approval = work.approvals.get(command.operation_id)
            if approval is None or approval.operation != operation:
                raise ApprovalBindingMismatch("APPROVAL_BINDING_MISMATCH")
            if approval.state != ApprovalState.PENDING:
                raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
            decided = approval.decide(command.principal, command.decision, self._clock.now())
            work.operations.save_approval_decision(decided.operation)
            work.approvals.save_decision(decided)
            work.audit.append(decided.decided_event())
            work.commit()
            return ApproveOperationResult(decided)
