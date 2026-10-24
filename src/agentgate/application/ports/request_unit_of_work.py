from types import TracebackType
from typing import Protocol

from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository


class RequestUnitOfWork(Protocol):
    rollback_confirmed: bool
    operations: OperationRepository
    accounts: AccountRepository
    approvals: ApprovalRepository
    audit: AuditRepository

    def set_deadline(self, deadline: ExecutionDeadline) -> None: ...

    def __enter__(self) -> "RequestUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
