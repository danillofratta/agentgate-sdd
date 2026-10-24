import sqlite3
from typing import cast

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.infrastructure.repositories.operation_mapper import hydrate


class SqliteOperationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def find(self, principal_id: PrincipalId, key: IdempotencyKey) -> Operation | None:
        row = cast(
            sqlite3.Row | None,
            self._connection.execute(
                "SELECT * FROM operations WHERE principal_id=? AND key=?",
                (principal_id.value, key.value),
            ).fetchone(),
        )
        return None if row is None else hydrate(row)

    def add(self, operation: Operation) -> None:
        self._connection.execute(
            """INSERT INTO operations(id, principal_id, key, request_json, fingerprint,
               decision, reason, policy_version, created_at, state) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                operation.state.value,
            ),
        )
