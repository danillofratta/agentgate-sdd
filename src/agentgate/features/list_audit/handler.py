from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.domain.repositories.audit_read_repository import AuditReadRepository
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.role import Role
from agentgate.features.list_audit.query import ListAuditQuery
from agentgate.features.list_audit.result import ListAuditResult


class ListAuditHandler:
    def __init__(self, repository: AuditReadRepository) -> None:
        self._repository = repository

    def handle(self, query: ListAuditQuery) -> ListAuditResult:
        if query.principal.role != Role.APPROVER:
            raise Forbidden
        events = self._repository.list(AuditPage(query.after, query.limit))
        return ListAuditResult(events, events[-1].id if events else query.after)
