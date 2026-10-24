from typing import Protocol

from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.events.operation_executed_event import OperationExecutedEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class AuditRepository(Protocol):
    def append(
        self,
        event: OperationRequestedEvent
        | ApprovalDecidedEvent
        | ApprovalExpiredEvent
        | OperationExecutedEvent
        | OperationDispatchedEvent,
    ) -> None: ...
