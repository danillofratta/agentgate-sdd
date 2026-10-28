from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.domain.entities.approval import Approval
from agentgate.domain.enums.approval_state import ApprovalState
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.exceptions.approval_binding_mismatch import ApprovalBindingMismatch
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.features.expire_approval.command import ExpireApprovalCommand


class ExpireApprovalHandler:
    def __init__(self, unit_of_work: RequestUnitOfWorkFactory, clock: ClockGateway) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def handle(self, command: ExpireApprovalCommand) -> Approval:
        with self._unit_of_work() as work:
            operation = work.operations.get(command.operation_id)
            if operation is None:
                raise NotFound
            if operation.id != command.operation_id:
                raise ApprovalBindingMismatch("APPROVAL_BINDING_MISMATCH")
            if operation.state not in {
                OperationState.PENDING_APPROVAL,
                OperationState.READY,
                OperationState.EXPIRED,
            }:
                raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
            approval = work.approvals.get(command.operation_id)
            if approval is None or approval.operation != operation:
                raise ApprovalBindingMismatch("APPROVAL_BINDING_MISMATCH")
            if approval.state == ApprovalState.EXPIRED:
                return approval
            now = self._clock.now()
            expired = approval.expire(now)
            work.operations.save_approval_expiry(expired.operation)
            work.approvals.save_expiry(expired)
            work.audit.append(expired.expired_event(now))
            work.commit()
            return expired
