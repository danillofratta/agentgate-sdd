from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.tool import Tool
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint


@dataclass(frozen=True)
class OperationFailedEvent:
    operation_id: OperationId
    principal_id: PrincipalId
    tool: Tool
    fingerprint: RequestFingerprint
    policy_version: PolicyVersion
    occurred_at: datetime

    state: OperationState

    def __post_init__(self) -> None:
        OperationDispatchedEvent(
            self.operation_id,
            self.principal_id,
            self.tool,
            self.fingerprint,
            self.policy_version,
            self.occurred_at,
        )
        if self.state not in (OperationState.FAILED, OperationState.TIMED_OUT):
            raise InvariantViolation("INVALID_EXECUTION_FAILURE")
