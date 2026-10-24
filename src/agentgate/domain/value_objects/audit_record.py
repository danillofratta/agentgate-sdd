from dataclasses import dataclass

from agentgate.domain.events.approval_decided_event import ApprovalDecidedEvent
from agentgate.domain.events.approval_expired_event import ApprovalExpiredEvent
from agentgate.domain.events.operation_requested_event import OperationRequestedEvent
from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class AuditRecord:
    """Persisted decision evidence; contains only validated identifiers and codes."""

    id: int
    event: OperationRequestedEvent | ApprovalDecidedEvent | ApprovalExpiredEvent

    def __post_init__(self) -> None:
        if type(self.id) is not int or not 1 <= self.id <= 2**63 - 1:
            raise InvariantViolation("INVALID_AUDIT_ID")
        if not isinstance(
            self.event, (OperationRequestedEvent, ApprovalDecidedEvent, ApprovalExpiredEvent)
        ):
            raise InvariantViolation("INVALID_AUDIT_EVENT")
