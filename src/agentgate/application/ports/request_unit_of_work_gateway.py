from types import TracebackType
from typing import Protocol

from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository


class RequestUnitOfWorkGateway(Protocol):
    operations: OperationRepository
    accounts: AccountRepository
    approvals: ApprovalRepository
    audit: AuditRepository

    def __enter__(self) -> "RequestUnitOfWorkGateway": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...
