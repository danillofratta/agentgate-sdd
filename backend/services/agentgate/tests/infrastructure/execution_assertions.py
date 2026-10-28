import sqlite3
from contextlib import closing

from agentgate.infrastructure.persistence.database import connect


def assert_rolled_back(database, before, *, state="READY", attempts=1):
    """Compare every business column and prior audit row, permitting only 5.5 evidence."""
    with closing(sqlite3.connect(":memory:")) as expected, closing(connect(database)) as actual:
        expected.executescript("\n".join(before))
        expected.row_factory = actual.row_factory = sqlite3.Row
        for table in ("accounts", "approvals"):
            assert [tuple(row) for row in actual.execute(f"SELECT * FROM {table}")] == [
                tuple(row) for row in expected.execute(f"SELECT * FROM {table}")
            ]
        old = [dict(row) for row in expected.execute("SELECT * FROM operations")]
        assert len(old) == 1
        old[0]["state"] = state
        assert [dict(row) for row in actual.execute("SELECT * FROM operations")] == old
        previous = [dict(row) for row in expected.execute("SELECT * FROM audit_events ORDER BY id")]
        current = [dict(row) for row in actual.execute("SELECT * FROM audit_events ORDER BY id")]
        assert current[: len(previous)] == previous
        added = current[len(previous) :]
        assert [
            row["attempt"] for row in added if row["event_type"] == "OPERATION_ATTEMPTED"
        ] == list(range(1, attempts + 1))
        terminal = state in ("FAILED", "TIMED_OUT")
        assert len(added) == attempts + int(terminal)
        assert all(
            row["event_type"] in ("OPERATION_ATTEMPTED", "OPERATION_FAILED") for row in added
        )
        if terminal:
            assert added[-1]["event_type"] == "OPERATION_FAILED"
            assert added[-1]["decision"] == state
            assert added[-1]["reason"] == "EXECUTION_" + state
