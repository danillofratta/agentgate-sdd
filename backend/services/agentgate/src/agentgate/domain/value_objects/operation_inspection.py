from dataclasses import dataclass

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.approval_inspection import ApprovalInspection
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


@dataclass(frozen=True)
class OperationInspection:
    operation: Operation
    approval: ApprovalInspection | None = None
    result: BalanceResult | TransferArguments | None = None
