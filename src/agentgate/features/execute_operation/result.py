from dataclasses import dataclass

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.balance_result import BalanceResult


@dataclass(frozen=True)
class ExecuteOperationResult:
    operation: Operation
    result: BalanceResult
