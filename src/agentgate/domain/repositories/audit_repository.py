from typing import Protocol

from agentgate.domain.events.operation_requested_event import OperationRequestedEvent


class AuditRepository(Protocol):
    def append(self, event: OperationRequestedEvent) -> None: ...
