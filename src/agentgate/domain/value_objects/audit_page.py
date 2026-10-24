from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation


@dataclass(frozen=True)
class AuditPage:
    after: int = 0
    limit: int = 50

    def __post_init__(self) -> None:
        if type(self.after) is not int or not 0 <= self.after <= 2**63 - 1:
            raise InvariantViolation("INVALID_AUDIT_CURSOR")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise InvariantViolation("INVALID_AUDIT_LIMIT")
