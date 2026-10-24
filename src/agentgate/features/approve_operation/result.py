from dataclasses import dataclass

from agentgate.domain.entities.approval import Approval


@dataclass(frozen=True)
class ApproveOperationResult:
    approval: Approval
