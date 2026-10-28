import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.enums.role import Role
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.list_audit.query import ListAuditQuery
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from tests.infrastructure.test_transactional_persistence import snapshot


def test_keyset_ordering_defaults_gaps_and_reopen(database, audit_history):
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM audit_events WHERE id=2")
    repository = SqliteAuditReadRepository(database)
    first = repository.list(AuditPage())
    assert len(first) == 50
    assert [record.id for record in first] == [1, *range(3, 52)]
    assert first[0].event == audit_history[0].requested_event()
    assert first[0].event.occurred_at > first[-1].event.occurred_at
    initialize(database)
    second = SqliteAuditReadRepository(database).list(AuditPage(first[-1].id, 100))
    assert [record.id for record in second] == list(range(52, 106))
    assert repository.list(AuditPage(105, 1)) == ()
    assert repository.list(AuditPage(2**63 - 1)) == ()
    with pytest.raises(FrozenInstanceError):
        first[0].id = 10


def test_repeated_queries_after_approval_expiry_preserve_every_table(
    database, audit_history, principal, clock
):
    before = snapshot(database)
    clock.value += timedelta(days=1)
    handler = ListAuditHandler(SqliteAuditReadRepository(database))
    query = ListAuditQuery(replace(principal, role=Role.APPROVER), after=50, limit=100)
    for _ in range(3):
        result = handler.handle(query)
        assert [record.id for record in result.events] == list(range(51, 106))
        assert result.next_after == 105
    assert snapshot(database) == before


def test_reader_sees_only_committed_events(database, audit_history):
    repository = SqliteAuditReadRepository(database)
    with SqliteUnitOfWork(database) as work:
        operation = replace(audit_history[0], key=IdempotencyKey("uncommitted"))
        # Audit can refer to an existing operation; this event remains transaction-bound.
        work.audit.append(operation.requested_event())
        assert repository.list(AuditPage(105)) == ()
        work.commit()
    assert [record.id for record in repository.list(AuditPage(105))] == [106]


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(StorageUnavailable) as error:
        SqliteAuditReadRepository(str(path)).list(AuditPage())
    assert str(error.value) == ""
    assert not path.exists()


def test_reader_uses_read_only_sqlite_connection(database, monkeypatch):
    original_connect = sqlite3.connect
    observed = []

    def inspect_connection(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        assert kwargs["uri"] is True
        assert args[0].endswith("?mode=ro")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM accounts")
        observed.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", inspect_connection)
    assert SqliteAuditReadRepository(database).list(AuditPage()) == ()
    assert len(observed) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed[0].execute("SELECT 1")


@pytest.mark.parametrize(
    "column",
    [
        "operation_id",
        "principal_id",
        "tool",
        "decision",
        "reason",
        "policy_version",
        "occurred_at",
        "event_type",
    ],
)
def test_corrupt_audit_fields_fail_safely(database, audit_history, column):
    sentinel = "SECRET_SENTINEL\nforged-log-record"
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE audit_events SET {column}=? WHERE id=1", (sentinel,))
    with pytest.raises(StorageUnavailable) as error:
        SqliteAuditReadRepository(database).list(AuditPage())
    assert str(error.value) == ""
