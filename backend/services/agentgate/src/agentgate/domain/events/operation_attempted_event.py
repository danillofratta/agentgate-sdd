from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.enums.tool import Tool
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint


@dataclass(frozen=True)
class OperationAttemptedEvent:
    """Durable transaction-attempt evidence, never evidence of a financial effect."""

    operation_id: OperationId
    principal_id: PrincipalId
    tool: Tool
    fingerprint: RequestFingerprint
    policy_version: PolicyVersion
    occurred_at: datetime

    attempt: int

    def __post_init__(self) -> None:
        OperationDispatchedEvent(
            self.operation_id,
            self.principal_id,
            self.tool,
            self.fingerprint,
            self.policy_version,
            self.occurred_at,
        )
        if type(self.attempt) is not int or not 1 <= self.attempt <= 2**63 - 1:
            raise InvariantViolation("INVALID_ATTEMPT")
