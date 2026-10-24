import sqlite3
from types import TracebackType
from typing import Self

from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository
from agentgate.infrastructure.persistence.database import connect
from agentgate.infrastructure.persistence.deadline_connection import DeadlineConnection
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
        self._deadline: ExecutionDeadline | None = None
        self._commit_started = False
        self.operations: OperationRepository
        self.accounts: AccountRepository
        self.approvals: ApprovalRepository
        self.audit: AuditRepository

    def set_deadline(self, deadline: ExecutionDeadline) -> None:
        if self._connection is not None:
            raise StorageUnavailable
        self._deadline = deadline

    def _raise_failure(self, error: sqlite3.Error, connection: sqlite3.Connection) -> None:
        if self._deadline is not None and not self._commit_started:
            if isinstance(connection, DeadlineConnection) and connection.interrupted:
                raise ExecutionTimedOut from None
            self._deadline.remaining()
            code = getattr(error, "sqlite_errorcode", None)
            if code is not None and (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise TransientStorageLock from None
        raise StorageUnavailable from None

    def __enter__(self) -> Self:
        if self._connection is not None:
            raise StorageUnavailable
        connection = connect(self._path)
        self._commit_started = False
        try:
            if self._deadline is not None:
                if not isinstance(connection, DeadlineConnection):
                    raise StorageUnavailable
                connection.deadline = self._deadline
                connection.set_progress_handler(connection.progress, 100)
            connection.execute("BEGIN IMMEDIATE")
        except BaseException as error:
            try:
                connection.set_progress_handler(None, 0)
                try:
                    connection.rollback()
                    if connection.in_transaction:
                        raise StorageUnavailable
                except sqlite3.Error:
                    raise StorageUnavailable from None
                if isinstance(error, sqlite3.Error):
                    self._raise_failure(error, connection)
                raise
            finally:
                connection.close()
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
            if self._deadline is not None:
                self._deadline.remaining()
                if isinstance(self._connection, DeadlineConnection):
                    self._connection.prepare()
                self._deadline.remaining()
            # Once commit is entered it may succeed after the deadline. Never interrupt
            # it or infer a rollback from a late acknowledgment.
            self._connection.set_progress_handler(None, 0)
            self._commit_started = True
            self._connection.commit()
        except sqlite3.Error:
            raise StorageUnavailable from None

    def rollback(self) -> None:
        if self._connection is None:
            raise StorageUnavailable
        try:
            self._connection.set_progress_handler(None, 0)
            self._connection.rollback()
            if self._connection.in_transaction:
                raise StorageUnavailable
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
                self.rollback()
                if isinstance(exc, sqlite3.Error):
                    self._raise_failure(exc, self._connection)
            finally:
                self._connection.close()
                self._connection = None
        if isinstance(exc, sqlite3.Error):
            raise StorageUnavailable from None
