from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.domain.enums.tool import Tool
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.infrastructure.tools.get_balance_adapter import GetBalanceAdapter
from agentgate.infrastructure.tools.simulate_transfer_adapter import SimulateTransferAdapter


class LocalToolRegistryGateway:
    """Fixed local registry with no transaction, credential, or dynamic-import capability."""

    def __init__(self, balance: GetBalanceAdapter, transfer: SimulateTransferAdapter) -> None:
        self._balance = balance
        self._transfer = transfer

    def dispatch(
        self,
        tool: Tool,
        arguments: BalanceArguments | TransferArguments,
        accounts: tuple[AccountFacts, ...],
    ) -> BalanceResult | TransferArguments:
        if tool == Tool.GET_BALANCE and type(arguments) is BalanceArguments:
            return self._balance.run(arguments, accounts)
        if tool == Tool.SIMULATE_TRANSFER and type(arguments) is TransferArguments:
            return self._transfer.run(arguments, accounts)
        raise ExecutionUnavailable
