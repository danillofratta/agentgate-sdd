from types import TracebackType
from typing import Any, Self

import psycopg
from psycopg import Connection
from psycopg.pq import TransactionStatus

from agentgate.application.exceptions.commit_uncertain import CommitUncertain
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository
from agentgate.infrastructure.persistence.postgres_database import WRITE_LOCK, connect
from agentgate.infrastructure.persistence.postgres_session import PostgresSession
from agentgate.infrastructure.repositories.postgres_account_repository import (
    PostgresAccountRepository,
)
from agentgate.infrastructure.repositories.postgres_approval_repository import (
    PostgresApprovalRepository,
)
from agentgate.infrastructure.repositories.postgres_audit_repository import PostgresAuditRepository
from agentgate.infrastructure.repositories.postgres_operation_repository import (
    PostgresOperationRepository,
)


class PostgresUnitOfWork:
    def __init__(self, database: str) -> None:
        self._database = database
        self._connection: Connection[dict[str, Any]] | None = None
        self._deadline: ExecutionDeadline | None = None
        self._commit_started = False
        self.rollback_confirmed = False
        self.operations: OperationRepository
        self.accounts: AccountRepository
        self.approvals: ApprovalRepository
        self.audit: AuditRepository

    def set_deadline(self, deadline: ExecutionDeadline) -> None:
        if self._connection is not None:
            raise StorageUnavailable
        self._deadline = deadline

    def _failure(self, error: psycopg.Error) -> None:
        if self._commit_started:
            raise CommitUncertain from None
        if self._deadline is not None:
            self._deadline.remaining()
            if self.rollback_confirmed and error.sqlstate in {"55P03", "40P01", "40001"}:
                raise TransientStorageLock from None
        raise StorageUnavailable from None

    def __enter__(self) -> Self:
        if self._connection is not None:
            raise StorageUnavailable
        self.rollback_confirmed = False
        self._commit_started = False
        if self._deadline is not None:
            self._deadline.remaining()
        connection = connect(self._database)
        self._connection = connection
        try:
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            if self._deadline is not None:
                milliseconds = max(1, int(self._deadline.remaining() * 1000))
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(milliseconds),)
                )
                connection.execute(
                    "SELECT set_config('lock_timeout', %s, true)",
                    (str(min(50, milliseconds)),),
                )
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
            if self._deadline is not None:
                self._deadline.remaining()
            session = PostgresSession(connection, self._deadline)
            self.operations = PostgresOperationRepository(session)
            self.accounts = PostgresAccountRepository(session)
            self.approvals = PostgresApprovalRepository(session)
            self.audit = PostgresAuditRepository(session)
            return self
        except BaseException as error:
            try:
                self.rollback()
            finally:
                connection.close()
                self._connection = None
            if isinstance(error, psycopg.Error):
                self._failure(error)
            raise

    def commit(self) -> None:
        if self._connection is None:
            raise StorageUnavailable
        if self._deadline is not None:
            self._deadline.remaining()
        try:
            # A late acknowledgment is not proof of rollback. Never cancel COMMIT.
            self._connection.execute("SET LOCAL statement_timeout=0")
            self._commit_started = True
            self._connection.commit()
        except psycopg.Error as error:
            self._failure(error)

    def rollback(self) -> None:
        if self._connection is None:
            raise StorageUnavailable
        try:
            self._connection.rollback()
            if self._connection.info.transaction_status != TransactionStatus.IDLE:
                raise StorageUnavailable
            self.rollback_confirmed = not self._commit_started
        except psycopg.Error:
            raise StorageUnavailable from None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._connection is None:
            return
        try:
            try:
                self.rollback()
            except Exception:
                if self._commit_started:
                    raise CommitUncertain from None
                raise StorageUnavailable from None
            if exc is not None and self._commit_started:
                raise CommitUncertain from None
            if isinstance(exc, psycopg.Error):
                self._failure(exc)
        finally:
            self._connection.close()
            self._connection = None
