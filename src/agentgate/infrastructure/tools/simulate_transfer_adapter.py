from typing import NoReturn

from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


class SimulateTransferAdapter:
    def run(self, arguments: TransferArguments, accounts: tuple[AccountFacts, ...]) -> NoReturn:
        # Fail closed until the atomic transfer increment is implemented.
        raise ExecutionUnavailable
