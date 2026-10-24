from dataclasses import dataclass

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


@dataclass(frozen=True)
class ExecuteOperationResult:
    operation: Operation
    result: BalanceResult | TransferArguments
