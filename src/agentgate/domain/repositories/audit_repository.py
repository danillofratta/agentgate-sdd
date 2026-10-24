from typing import Protocol

from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class AuditRepository(Protocol):
    def append(
        self, event: OperationRequestedEvent | ApprovalDecidedEvent | ApprovalExpiredEvent
    ) -> None: ...
