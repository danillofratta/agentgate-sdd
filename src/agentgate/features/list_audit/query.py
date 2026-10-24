from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class ListAuditQuery:
    principal: Principal
    after: int = 0
    limit: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.principal, Principal):
            raise InvariantViolation("INVALID_QUERY")
        AuditPage(self.after, self.limit)
