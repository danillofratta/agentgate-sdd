import sqlite3
from typing import cast

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.operation import Operation
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.infrastructure.repositories.operation_mapper import hydrate
from agentgate.infrastructure.repositories.sqlite_approval_repository import (
    SqliteApprovalRepository,
)


class SqliteOperationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, operation_id: OperationId) -> Operation | None:
        row = self._connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id.value,)
        ).fetchone()
        return None if row is None else hydrate(row, stored_state=True)

    def save_approval_decision(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if operation.state not in {OperationState.READY, OperationState.REJECTED}:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        if operation.policy.decision != Decision.REQUIRE_APPROVAL:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        cursor = self._connection.execute(
            """UPDATE operations SET state=? WHERE id=? AND state='PENDING_APPROVAL'
               AND principal_id=? AND key=? AND request_json=? AND fingerprint=?
               AND decision=? AND reason=? AND policy_version=? AND created_at=?""",
            (
                operation.state.value,
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def find(self, principal_id: PrincipalId, key: IdempotencyKey) -> Operation | None:
        row = cast(
            sqlite3.Row | None,
            self._connection.execute(
                "SELECT * FROM operations WHERE principal_id=? AND key=?",
                (principal_id.value, key.value),
            ).fetchone(),
        )
        if row is None:
            return None
        operation = hydrate(row, stored_state=True)
        if (
            operation.policy.decision == Decision.REQUIRE_APPROVAL
            and operation.state != OperationState.PENDING_APPROVAL
        ):
            approval = SqliteApprovalRepository(self._connection).get(operation.id)
            if approval is None or approval.operation != operation:
                raise StorageUnavailable
        return operation

    def save_approval_expiry(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if (
            operation.state != OperationState.EXPIRED
            or operation.policy.decision != Decision.REQUIRE_APPROVAL
        ):
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        cursor = self._connection.execute(
            """UPDATE operations SET state='EXPIRED'
               WHERE id=? AND state IN ('PENDING_APPROVAL','READY') AND result_json IS NULL
               AND principal_id=? AND key=? AND request_json=? AND fingerprint=?
               AND decision=? AND reason=? AND policy_version=? AND created_at=?""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def add(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        self._connection.execute(
            """INSERT INTO operations(id, principal_id, key, request_json, fingerprint,
               decision, reason, policy_version, created_at, state) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                operation.state.value,
            ),
        )
