from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.enums.tool import Tool
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint
from agentgate.domain.value_objects.utc import require_utc


@dataclass(frozen=True)
class ApprovalExpiredEvent:
    """Expiry observed by an internal command, without a human decision."""

    operation_id: OperationId
    principal_id: PrincipalId
    tool: Tool
    fingerprint: RequestFingerprint
    policy_version: PolicyVersion
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not (
            isinstance(self.operation_id, OperationId)
            and isinstance(self.principal_id, PrincipalId)
            and isinstance(self.tool, Tool)
            and isinstance(self.fingerprint, RequestFingerprint)
            and isinstance(self.policy_version, PolicyVersion)
        ):
            raise InvariantViolation("INVALID_APPROVAL_EVENT")
        require_utc(self.occurred_at)
