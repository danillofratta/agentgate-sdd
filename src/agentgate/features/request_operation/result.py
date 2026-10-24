from dataclasses import dataclass

from agentgate.domain.entities.operation import Operation


@dataclass(frozen=True)
class RequestOperationResult:
    operation: Operation
    created: bool
