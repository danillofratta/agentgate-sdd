from typing import Protocol

from agentgate.domain.entities.approval import Approval


class ApprovalRepository(Protocol):
    def add(self, approval: Approval) -> None: ...
