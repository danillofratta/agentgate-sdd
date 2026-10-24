from dataclasses import dataclass
from datetime import datetime, timedelta

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.decision import Decision


@dataclass(frozen=True)
class Approval:
    """Pending approval bound to one immutable operation; no grant capability yet."""

    operation: Operation

    def __post_init__(self) -> None:
        from agentgate.domain.exceptions.invariant_violation import InvariantViolation

        if (
            not isinstance(self.operation, Operation)
            or self.operation.policy.decision != Decision.REQUIRE_APPROVAL
        ):
            raise InvariantViolation("APPROVAL_NOT_REQUIRED")

    @property
    def expires_at(self) -> datetime:
        return self.operation.created_at + timedelta(seconds=300)
