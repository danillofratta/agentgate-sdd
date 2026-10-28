import sqlite3
from typing import Any

from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.execution_deadline import ExecutionDeadline


class DeadlineConnection(sqlite3.Connection):
    """Guard the statements used by transaction repositories, without owning commits."""

    deadline: ExecutionDeadline | None = None
    interrupted: bool = False

    def prepare(self) -> None:
        if self.deadline is not None:
            milliseconds = int(min(0.05, self.deadline.remaining()) * 1000)
            super().execute(f"PRAGMA busy_timeout={milliseconds}")

    def progress(self) -> int:
        if self.deadline is not None:
            try:
                self.deadline.remaining()
            except ExecutionTimedOut:
                self.interrupted = True
                return 1
        return 0

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        self.prepare()
        return super().execute(sql, parameters)
