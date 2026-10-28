from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


class SimulateTransferAdapter:
    def run(
        self, arguments: TransferArguments, accounts: tuple[AccountFacts, ...]
    ) -> TransferArguments:
        known = {account.id for account in accounts}
        if (
            arguments.source_account_id not in known
            or arguments.destination_account_id not in known
        ):
            raise ExecutionUnavailable
        # The established exact transfer result schema is the immutable transfer value.
        # Account transitions and persistence remain inside the caller's unit of work.
        return arguments
