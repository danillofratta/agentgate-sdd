from contextlib import closing
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable

WRITE_LOCK = 7619471001
SCHEMA_LOCK = 7619471002

SCHEMA = (
    """CREATE TABLE accounts (
        id TEXT PRIMARY KEY, balance_cents BIGINT NOT NULL CHECK(balance_cents >= 0))""",
    """CREATE TABLE operations (
        id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, key TEXT NOT NULL,
        request_json TEXT NOT NULL, fingerprint TEXT NOT NULL, decision TEXT NOT NULL,
        reason TEXT NOT NULL, policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
        state TEXT NOT NULL, result_json TEXT, authorization_json TEXT,
        UNIQUE(principal_id, key))""",
    """CREATE TABLE approvals (
        operation_id TEXT PRIMARY KEY REFERENCES operations(id),
        principal_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL, status TEXT NOT NULL
        CHECK(status IN ('PENDING','GRANTED','REJECTED','EXPIRED','CONSUMED')),
        decision TEXT, approver_id TEXT, decided_at TEXT, consumed_at TEXT,
        CHECK((status='CONSUMED' AND consumed_at IS NOT NULL) OR
              (status!='CONSUMED' AND consumed_at IS NULL)),
        CHECK((status IN ('PENDING','EXPIRED') AND decision IS NULL
               AND approver_id IS NULL AND decided_at IS NULL) OR
              (status IN ('GRANTED','REJECTED','EXPIRED','CONSUMED') AND decision IS NOT NULL
               AND approver_id IS NOT NULL AND decided_at IS NOT NULL
               AND approver_id != principal_id AND
               ((status IN ('GRANTED','EXPIRED','CONSUMED') AND decision='APPROVE') OR
                (status='REJECTED' AND decision='REJECT')))))""",
    """CREATE TABLE audit_events (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES operations(id), principal_id TEXT NOT NULL,
        tool TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
        policy_version TEXT NOT NULL, occurred_at TEXT NOT NULL, event_type TEXT NOT NULL,
        approver_id TEXT, fingerprint TEXT, attempt BIGINT,
        CHECK((event_type='OPERATION_ATTEMPTED' AND attempt IS NOT NULL
               AND attempt > 0 AND decision='ALLOW' AND reason='EXECUTION_ATTEMPT') OR
              (event_type!='OPERATION_ATTEMPTED' AND attempt IS NULL)),
        UNIQUE(operation_id, attempt))""",
)


def connect(database: str) -> Connection[dict[str, Any]]:
    try:
        return psycopg.connect(
            database,
            row_factory=dict_row,
            connect_timeout=2,
            options="-c statement_timeout=2000 -c lock_timeout=1000",
        )
    except psycopg.Error:
        raise StorageUnavailable from None


def begin_read(connection: Connection[dict[str, Any]]) -> None:
    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def initialize(database: str, *, seed: bool = False) -> None:
    try:
        with closing(connect(database)) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agentgate_schema (version INTEGER PRIMARY KEY)"
            )
            versions = connection.execute("SELECT version FROM agentgate_schema").fetchall()
            if not versions:
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.execute("INSERT INTO agentgate_schema VALUES (1)")
            elif versions != [{"version": 1}]:
                raise StorageUnavailable
            if seed:
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
                for account in ("acct-alice", "acct-bob"):
                    connection.execute(
                        "INSERT INTO accounts VALUES (%s,1000000) ON CONFLICT (id) DO NOTHING",
                        (account,),
                    )
            connection.commit()
    except psycopg.Error:
        raise StorageUnavailable from None
