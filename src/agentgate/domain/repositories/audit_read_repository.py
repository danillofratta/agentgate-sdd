from typing import Protocol

from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.audit_record import AuditRecord


class AuditReadRepository(Protocol):
    def list(self, page: AuditPage) -> tuple[AuditRecord, ...]: ...
