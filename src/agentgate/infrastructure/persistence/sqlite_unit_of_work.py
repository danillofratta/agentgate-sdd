import sqlite3
from types import TracebackType
from typing import Self

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository
from agentgate.infrastructure.persistence.database import connect
from agentgate.infrastructure.repositories.sqlite_account_repository import SqliteAccountRepository
from agentgate.infrastructure.repositories.sqlite_approval_repository import (
    SqliteApprovalRepository,
)
from agentgate.infrastructure.repositories.sqlite_audit_repository import SqliteAuditRepository
from agentgate.infrastructure.repositories.sqlite_operation_repository import (
    SqliteOperationRepository,
)


class SqliteUnitOfWork:
    def __init__(self, path: str) -> None:
        self._path = path
        self._connection: sqlite3.Connection | None = None
        self.operations: OperationRepository
        self.accounts: AccountRepository
        self.approvals: ApprovalRepository
        self.audit: AuditRepository

    def __enter__(self) -> Self:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            connection.close()
            raise StorageUnavailable from None
        self._connection = connection
        self.operations = SqliteOperationRepository(connection)
        self.accounts = SqliteAccountRepository(connection)
        self.approvals = SqliteApprovalRepository(connection)
        self.audit = SqliteAuditRepository(connection)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise StorageUnavailable
        try:
            self._connection.commit()
        except sqlite3.Error:
            raise StorageUnavailable from None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._connection is not None:
            try:
                self._connection.rollback()
            finally:
                self._connection.close()
                self._connection = None
        if isinstance(exc, sqlite3.Error):
            raise StorageUnavailable from None
