from dataclasses import dataclass

from agentgate.domain.value_objects.audit_record import AuditRecord


@dataclass(frozen=True)
class ListAuditResult:
    events: tuple[AuditRecord, ...]
    next_after: int
