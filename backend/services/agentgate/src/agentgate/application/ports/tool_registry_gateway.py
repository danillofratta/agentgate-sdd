from typing import Protocol

from agentgate.domain.enums.tool import Tool
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


class ToolRegistryGateway(Protocol):
    def dispatch(
        self,
        tool: Tool,
        arguments: BalanceArguments | TransferArguments,
        accounts: tuple[AccountFacts, ...],
    ) -> BalanceResult | TransferArguments: ...
