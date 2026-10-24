import sqlite3

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable

LEGACY_SCHEMA = (
    """CREATE TABLE accounts (
        id TEXT PRIMARY KEY, balance_cents INTEGER NOT NULL
        CHECK(typeof(balance_cents)='integer' AND balance_cents >= 0))""",
    """CREATE TABLE operations (
        id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, key TEXT NOT NULL,
        request_json TEXT NOT NULL, fingerprint TEXT NOT NULL, decision TEXT NOT NULL,
        reason TEXT NOT NULL, policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
        state TEXT NOT NULL, UNIQUE(principal_id, key))""",
    """CREATE TABLE approvals (
        operation_id TEXT PRIMARY KEY REFERENCES operations(id),
        principal_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='PENDING'))""",
    """CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id TEXT NOT NULL REFERENCES operations(id),
        principal_id TEXT NOT NULL,
        tool TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
        policy_version TEXT NOT NULL, occurred_at TEXT NOT NULL,
        event_type TEXT NOT NULL)""",
)

SCHEMA = (
    LEGACY_SCHEMA[0],
    LEGACY_SCHEMA[1].replace("state TEXT NOT NULL,", "state TEXT NOT NULL, result_json TEXT,"),
    *LEGACY_SCHEMA[2:],
)


def connect(path: str) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path, timeout=0.05, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error:
        raise StorageUnavailable from None


def initialize(path: str, *, seed: bool = False) -> None:
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise StorageUnavailable
        objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_schema WHERE substr(name, 1, 7) != 'sqlite_'"
        ).fetchall()
        if version == 0 and objects:
            raise StorageUnavailable
        if version in (1, 2):
            expected = {
                ("table", statement.split()[2]): " ".join(statement.split())
                for statement in (LEGACY_SCHEMA if version == 1 else SCHEMA)
            }
            actual = {
                (row["type"], row["name"]): " ".join((row["sql"] or "").split()) for row in objects
            }
            if actual != expected:
                raise StorageUnavailable
        if version == 0:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 2")
        if version == 1:
            # Inspection requires storage for results; commands remain separately scoped.
            connection.execute("ALTER TABLE operations ADD COLUMN result_json TEXT")
            connection.execute("PRAGMA user_version = 2")
        if seed:
            connection.executemany(
                "INSERT OR IGNORE INTO accounts(id, balance_cents) VALUES (?, ?)",
                [("acct-alice", 1000000), ("acct-bob", 1000000)],
            )
        connection.commit()
    except (sqlite3.Error, StorageUnavailable):
        connection.rollback()
        raise StorageUnavailable from None
    finally:
        connection.close()
