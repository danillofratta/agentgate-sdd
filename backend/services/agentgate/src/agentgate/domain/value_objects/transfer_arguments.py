from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.money import Money


@dataclass(frozen=True)
class TransferArguments:
    source_account_id: AccountId
    destination_account_id: AccountId
    amount: Money

    def __post_init__(self) -> None:
        if not isinstance(self.source_account_id, AccountId) or not isinstance(
            self.destination_account_id, AccountId
        ):
            raise InvariantViolation("INVALID_ACCOUNT_ID")
        if not isinstance(self.amount, Money):
            raise InvariantViolation("INVALID_AMOUNT")
        if self.source_account_id == self.destination_account_id:
            raise InvariantViolation("SAME_ACCOUNT_TRANSFER")
