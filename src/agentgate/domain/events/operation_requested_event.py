from dataclasses import dataclass
from datetime import datetime

from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.tool import Tool
from agentgate.domain.value_objects.utc import require_utc


@dataclass(frozen=True)
class OperationRequestedEvent:
    operation_id: OperationId
    principal_id: PrincipalId
    tool: Tool
    policy: PolicyDecision
    occurred_at: datetime

    def __post_init__(self) -> None:
        require_utc(self.occurred_at)
