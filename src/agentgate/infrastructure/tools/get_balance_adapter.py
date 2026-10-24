from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult


class GetBalanceAdapter:
    def run(self, arguments: BalanceArguments, accounts: tuple[AccountFacts, ...]) -> BalanceResult:
        matches = tuple(account for account in accounts if account.id == arguments.account_id)
        if len(matches) != 1:
            raise ExecutionUnavailable
        return BalanceResult(arguments.account_id, matches[0].balance_cents, "USD")
