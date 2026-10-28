from contextlib import closing

import psycopg

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_inspection import OperationInspection
from agentgate.infrastructure.persistence.postgres_database import begin_read, connect
from agentgate.infrastructure.repositories.operation_inspection_mapper import _approval, _result
from agentgate.infrastructure.repositories.operation_mapper import hydrate


class PostgresOperationReadRepository:
    def __init__(self, database: str) -> None:
        self._database = database

    def get(self, operation_id: OperationId) -> OperationInspection | None:
        try:
            with closing(connect(self._database)) as connection:
                begin_read(connection)
                row = connection.execute(
                    "SELECT * FROM operations WHERE id=%s", (operation_id.value,)
                ).fetchone()
                if row is None:
                    return None
                operation = hydrate(row, stored_state=True)
                approval = connection.execute(
                    "SELECT * FROM approvals WHERE operation_id=%s", (operation_id.value,)
                ).fetchone()
                return OperationInspection(
                    operation,
                    _approval(operation, approval),
                    _result(operation, row["result_json"]),
                )
        except (psycopg.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
