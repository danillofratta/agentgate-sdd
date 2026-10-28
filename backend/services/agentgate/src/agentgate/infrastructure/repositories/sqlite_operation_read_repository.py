import sqlite3
from contextlib import closing
from pathlib import Path

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_inspection import OperationInspection
from agentgate.infrastructure.repositories.operation_inspection_mapper import _approval, _result
from agentgate.infrastructure.repositories.operation_mapper import hydrate


class SqliteOperationReadRepository:
    def __init__(self, path: str) -> None:
        self._uri = Path(path).resolve().as_uri() + "?mode=ro"

    def get(self, operation_id: OperationId) -> OperationInspection | None:
        try:
            with closing(
                sqlite3.connect(self._uri, uri=True, timeout=0.05, isolation_level=None)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                # A single read transaction gives both rows one consistent snapshot.
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT * FROM operations WHERE id=?", (operation_id.value,)
                ).fetchone()
                if row is None:
                    return None
                operation = hydrate(row, stored_state=True)
                approval = connection.execute(
                    "SELECT * FROM approvals WHERE operation_id=?", (operation_id.value,)
                ).fetchone()
                return OperationInspection(
                    operation,
                    _approval(operation, approval),
                    _result(operation, row["result_json"]),
                )
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
