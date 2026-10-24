"""Disposable verification of the operator procedure in docs/persistence.md."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.database import LEGACY_SCHEMA, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.domain.test_request_values import transfer
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture
from tests.infrastructure.test_transactional_persistence import persist, snapshot

operation = operation_fixture


def checked_copy(source: Path, candidate: Path):
    """Procedure steps 2–4; never open a destination that already exists."""
    # Exclusive creation also prevents accidentally selecting the source itself.
    with candidate.open("xb"):
        pass
    try:
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(candidate)) as dst,
        ):
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise StorageUnavailable
            if dst.execute("PRAGMA foreign_key_check").fetchall():
                raise StorageUnavailable
    except (sqlite3.Error, StorageUnavailable):
        candidate.unlink()
        raise StorageUnavailable from None


def recovery_candidate(backup: Path, candidate: Path):
    checked_copy(backup, candidate)
    try:
        initialize(str(candidate), seed=False)
    except StorageUnavailable:
        candidate.unlink()
        raise


class UnusedIds:
    def next_id(self):
        pytest.fail("restored idempotent replay must not allocate an operation")


def test_backup_restore_reopen_preserves_all_data(database, tmp_path, operation, principal, clock):
    completed = replace(
        operation,
        id=OperationId("00000000-0000-4000-8000-000000000002"),
        key=IdempotencyKey("completed"),
        policy=PolicyDecision(Decision.ALLOW, Reason.PERMITTED, operation.policy.version),
    )
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.operations.add(completed)
        work.audit.append(completed.requested_event())
        work.commit()
    # Existing readers support durable results; execution remains a later task.
    args = completed.request.arguments
    payload = {
        "source_account_id": args.source_account_id.value,
        "destination_account_id": args.destination_account_id.value,
        "amount_cents": args.amount.cents,
        "currency": "USD",
    }
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE operations SET state='SUCCEEDED', result_json=? WHERE id=?",
            (json.dumps(payload), completed.id.value),
        )
        connection.execute("UPDATE accounts SET balance_cents=987654 WHERE id='acct-alice'")
        connection.execute("UPDATE accounts SET balance_cents=1012346 WHERE id='acct-bob'")
        connection.commit()
    expected = snapshot(database)
    expected_views = [
        SqliteOperationReadRepository(database).get(item.id) for item in (operation, completed)
    ]
    expected_audit = SqliteAuditReadRepository(database).list(AuditPage())
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "recovered.sqlite3"
    checked_copy(Path(database), backup)
    backup_bytes = backup.read_bytes()
    # A later committed change must not appear in the selected recovery point.
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE accounts SET balance_cents=0")
        connection.commit()
    recovery_candidate(backup, restored)
    for _ in range(3):
        initialize(str(restored))
        assert snapshot(str(restored)) == expected
        assert [
            SqliteOperationReadRepository(str(restored)).get(item.id)
            for item in (operation, completed)
        ] == expected_views
        assert SqliteAuditReadRepository(str(restored)).list(AuditPage()) == expected_audit
        with SqliteUnitOfWork(str(restored)) as work:
            assert work.operations.find(principal.id, operation.key) == operation
            assert work.operations.find(PrincipalId("principal-other"), operation.key) is None
            assert {fact.id.value: fact.balance_cents for fact in work.accounts.facts()} == {
                "acct-alice": 987654,
                "acct-bob": 1012346,
            }
        with closing(sqlite3.connect(restored)) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert expected_views[0].approval is not None
    assert expected_views[1].operation.state == OperationState.SUCCEEDED
    assert expected_views[1].result == completed.request.arguments
    handler = RequestOperationHandler(
        lambda: SqliteUnitOfWork(str(restored)), EvaluatePolicyHandler(), clock, UnusedIds()
    )
    replay = handler.handle(RequestOperationCommand(principal, operation.key, operation.request))
    assert replay.operation == operation
    assert replay.created is False
    with pytest.raises(IdempotencyConflict):
        handler.handle(RequestOperationCommand(principal, operation.key, transfer(1)))
    assert snapshot(str(restored)) == expected
    assert backup.read_bytes() == backup_bytes


def test_backup_includes_committed_wal_and_excludes_uncommitted_changes(database, tmp_path):
    with closing(sqlite3.connect(database, isolation_level=None)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE accounts SET balance_cents=123 WHERE id='acct-alice'")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE accounts SET balance_cents=456 WHERE id='acct-alice'")
        assert Path(database + "-wal").stat().st_size > 0
        candidate = tmp_path / "wal-backup.sqlite3"
        checked_copy(Path(database), candidate)
        writer.rollback()
    initialize(str(candidate))
    with SqliteUnitOfWork(str(candidate)) as work:
        assert {fact.id.value: fact.balance_cents for fact in work.accounts.facts()} == {
            "acct-alice": 123,
            "acct-bob": 1000000,
        }


@pytest.mark.parametrize("damage", ["corrupt", "version", "schema", "foreign_key", "missing"])
def test_bad_backup_is_rejected_before_promotion(database, tmp_path, damage):
    live = Path(database)
    original = live.read_bytes()
    backup = tmp_path / "bad.sqlite3"
    if damage == "corrupt":
        backup.write_bytes(b"corrupt-secret-sentinel\x00" * 100)
    elif damage != "missing":
        checked_copy(live, backup)
        with closing(sqlite3.connect(backup)) as connection:
            if damage == "version":
                connection.execute("PRAGMA user_version=999")
            elif damage == "schema":
                connection.execute("CREATE TABLE unexpected (secret TEXT)")
            else:
                connection.execute(
                    "INSERT INTO approvals VALUES ('missing','principal-agent','hash','v1',"
                    "'time','time','PENDING',NULL,NULL,NULL)"
                )
            connection.commit()
    before = backup.read_bytes() if backup.exists() else None
    candidate = tmp_path / "rejected.sqlite3"
    with pytest.raises(StorageUnavailable) as error:
        recovery_candidate(backup, candidate)
    assert str(error.value) == ""
    assert not candidate.exists()
    assert live.read_bytes() == original
    assert (backup.read_bytes() if backup.exists() else None) == before


def test_existing_destination_is_never_overwritten(database, tmp_path):
    for destination in (Path(database), tmp_path / "existing.sqlite3"):
        if not destination.exists():
            destination.write_bytes(b"preserve")
        before = destination.read_bytes()
        with pytest.raises(FileExistsError):
            checked_copy(Path(database), destination)
        assert destination.read_bytes() == before


def test_legacy_restore_migrates_candidate_only(tmp_path, operation):
    backup = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(backup)) as connection:
        for statement in LEGACY_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    with SqliteUnitOfWork(str(backup)) as work:
        persist(work, operation)
        work.commit()
    before = backup.read_bytes()
    candidate = tmp_path / "upgraded.sqlite3"
    recovery_candidate(backup, candidate)
    assert backup.read_bytes() == before
    assert SqliteOperationReadRepository(str(candidate)).get(operation.id).operation == operation
    with closing(sqlite3.connect(candidate)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
