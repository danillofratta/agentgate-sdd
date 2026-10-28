from collections.abc import Sequence
from typing import Any

from psycopg import Connection, Cursor
from psycopg.pq import TransactionStatus

from agentgate.application.execution_deadline import ExecutionDeadline


class PostgresSession:
    """Bound each repository statement by the remaining monotonic execution budget."""

    def __init__(
        self, connection: Connection[dict[str, Any]], deadline: ExecutionDeadline | None
    ) -> None:
        self._connection = connection
        self._deadline = deadline

    @property
    def in_transaction(self) -> bool:
        return self._connection.info.transaction_status == TransactionStatus.INTRANS

    def execute(
        self, query: str, parameters: Sequence[Any] | None = None
    ) -> Cursor[dict[str, Any]]:
        if self._deadline is not None:
            milliseconds = max(1, int(self._deadline.remaining() * 1000))
            self._connection.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(milliseconds),)
            )
        return self._connection.execute(query, parameters)
