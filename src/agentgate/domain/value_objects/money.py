from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class Money:
    cents: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if type(self.cents) is not int or not 1 <= self.cents <= 2**63 - 1:
            raise InvariantViolation("INVALID_AMOUNT")
        if type(self.currency) is not str or self.currency != "USD":
            raise InvariantViolation("INVALID_CURRENCY")
