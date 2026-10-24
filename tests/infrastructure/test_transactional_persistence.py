"""Contracts for the current request repositories and their transaction boundary."""

import json
import sqlite3
from dataclasses import replace

import pytest

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.ports.request_unit_of_work import RequestUnitOfWork
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.approval_repository import ApprovalRepository
from agentgate.domain.repositories.audit_repository import AuditRepository
from agentgate.domain.repositories.operation_repository import OperationRepository
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from tests.domain.test_request_values import transfer


@pytest.fixture
def operation(principal, clock):
    return Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("one"),
        transfer(),
        PolicyDecision(Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")),
        clock.now(),
    )


def snapshot(database):
    with sqlite3.connect(database) as connection:
        return tuple(connection.iterdump())


def persist(work: RequestUnitOfWork, operation):
    operations: OperationRepository = work.operations
    approvals: ApprovalRepository = work.approvals
    audit: AuditRepository = work.audit
    operations.add(operation)
    approvals.add(Approval(operation))
    audit.append(operation.requested_event())


def test_repository_contracts_share_uncommitted_connection_and_reopen(database, operation):
    with SqliteUnitOfWork(database) as work:
        accounts: AccountRepository = work.accounts
        assert {fact.id.value: fact.balance_cents for fact in accounts.facts()} == {
            "acct-alice": 1000000,
            "acct-bob": 1000000,
        }
        persist(work, operation)
        assert work.operations.find(operation.principal_id, operation.key) == operation
        assert work.operations.find(PrincipalId("principal-other"), operation.key) is None
        assert work.operations.find(operation.principal_id, IdempotencyKey("missing")) is None
        # Independent observers cannot see any repository's writes before UoW commit.
        with sqlite3.connect(database) as observer:
            for table in ("operations", "approvals", "audit_events"):
                assert observer.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        work.commit()

    initialize(database)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.operations.find(operation.principal_id, operation.key) == operation
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        approval = connection.execute("SELECT * FROM approvals").fetchone()
        assert dict(approval) == {
            "operation_id": operation.id.value,
            "principal_id": operation.principal_id.value,
            "fingerprint": operation.request.fingerprint.value,
            "policy_version": "v1",
            "created_at": operation.created_at.isoformat(),
            "expires_at": Approval(operation).expires_at.isoformat(),
            "status": "PENDING",
            "decision": None,
            "approver_id": None,
            "decided_at": None,
            "consumed_at": None,
        }
        audit = connection.execute("SELECT * FROM audit_events").fetchone()
        assert dict(audit) == {
            "id": 1,
            "operation_id": operation.id.value,
            "principal_id": operation.principal_id.value,
            "tool": operation.request.tool.value,
            "decision": operation.policy.decision.value,
            "reason": operation.policy.reason.value,
            "policy_version": "v1",
            "occurred_at": operation.created_at.isoformat(),
            "event_type": "OPERATION_REQUESTED",
            "approver_id": None,
            "fingerprint": None,
        }


@pytest.mark.parametrize("outcome", ["implicit", "explicit", "exception"])
def test_all_repository_writes_roll_back(database, operation, outcome):
    before = snapshot(database)
    try:
        with SqliteUnitOfWork(database) as work:
            persist(work, operation)
            if outcome == "explicit":
                work.rollback()
                assert work.operations.find(operation.principal_id, operation.key) is None
            if outcome == "exception":
                raise RuntimeError("injected failure")
    except RuntimeError:
        assert outcome == "exception"
    assert snapshot(database) == before


def test_real_audit_constraint_failure_rolls_back_every_write(database, operation):
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        with SqliteUnitOfWork(database) as work:
            persist(work, operation)
            # The operation PK is present, but this different event has no parent.
            work.audit.append(
                replace(
                    operation.requested_event(),
                    operation_id=OperationId("00000000-0000-4000-8000-000000000002"),
                )
            )
            work.commit()
    assert str(error.value) == ""
    assert snapshot(database) == before


@pytest.mark.parametrize("finish", ["commit", "rollback"])
@pytest.mark.parametrize("repository", ["operations", "approvals", "audit"])
def test_repository_writes_require_an_active_transaction(database, operation, finish, repository):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        getattr(work, finish)()
        before = snapshot(database)
        with pytest.raises(StorageUnavailable):
            if repository == "operations":
                work.operations.add(operation)
            elif repository == "approvals":
                work.approvals.add(Approval(operation))
            else:
                work.audit.append(operation.requested_event())
        assert snapshot(database) == before


def test_duplicate_operation_rolls_back_all_repository_writes(database, operation):
    before = snapshot(database)
    with pytest.raises(StorageUnavailable):
        with SqliteUnitOfWork(database) as work:
            persist(work, operation)
            work.operations.add(
                replace(operation, id=OperationId("00000000-0000-4000-8000-000000000002"))
            )
            work.commit()
    assert snapshot(database) == before


def test_commit_failure_rolls_back(database, operation, monkeypatch):
    from agentgate.infrastructure.persistence import sqlite_unit_of_work

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("secret-commit-sentinel")

    def connect(path):
        connection = sqlite3.connect(path, isolation_level=None, factory=FailingCommit)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    before = snapshot(database)
    monkeypatch.setattr(sqlite_unit_of_work, "connect", connect)
    with pytest.raises(StorageUnavailable) as error:
        with SqliteUnitOfWork(database) as work:
            persist(work, operation)
            work.commit()
    assert str(error.value) == ""
    assert snapshot(database) == before


@pytest.mark.parametrize("balance", [-1, 1.5, "invalid", None])
def test_balance_storage_constraints(database, balance):
    before = snapshot(database)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE accounts SET balance_cents=?", (balance,))
    assert snapshot(database) == before


def test_seed_is_explicit_and_repeated_seed_preserves_all_state(tmp_path, operation):
    database = str(tmp_path / "explicit.sqlite3")
    initialize(database)
    with SqliteUnitOfWork(database) as work:
        assert work.accounts.facts() == ()
    initialize(database, seed=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE accounts SET balance_cents=0 WHERE id='acct-alice'")
        connection.execute("INSERT INTO accounts VALUES (?,?)", ("acct-custom", 42))
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    before = snapshot(database)
    for _ in range(3):
        initialize(database, seed=True)
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "damage",
    [
        "PRAGMA user_version=0",
        "PRAGMA user_version=999",
        "DROP TABLE audit_events",
        "ALTER TABLE accounts ADD COLUMN unexpected TEXT",
        "CREATE TABLE unknown (value TEXT)",
        "DROP TABLE accounts; CREATE TABLE accounts (id TEXT PRIMARY KEY, balance_cents INTEGER)",
        "CREATE VIEW unexpected AS SELECT * FROM accounts",
        "CREATE TRIGGER unexpected AFTER INSERT ON accounts BEGIN DELETE FROM accounts; END",
    ],
)
def test_unknown_schema_rejected_before_seed_without_data_loss(database, damage):
    with sqlite3.connect(database) as connection:
        connection.executescript(damage)
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        initialize(database, seed=True)
    assert str(error.value) == ""
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "column,value",
    [
        ("fingerprint", "0" * 64),
        ("state", "UNKNOWN"),
        ("state", "READY"),
        ("decision", "UNKNOWN"),
        ("created_at", "invalid-secret-sentinel"),
        ("created_at", "2026-10-24T12:00:00"),
        ("request_json", "{}"),
        ("request_json", "null"),
        ("request_json", "not-json"),
        ("request_json", json.dumps({"tool": "unknown", "arguments": {}})),
        ("request_json", json.dumps({"tool": "simulate_transfer", "arguments": []})),
    ],
)
def test_invalid_stored_operation_fails_safely(database, operation, column, value):
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE operations SET {column}=?", (value,))
    with pytest.raises(StorageUnavailable) as error:
        with SqliteUnitOfWork(database) as work:
            work.operations.find(operation.principal_id, operation.key)
    assert str(error.value) == ""


def test_balance_request_round_trip(database, principal, clock):
    operation = Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("balance"),
        OperationRequest(BalanceArguments(AccountId("acct-alice"))),
        PolicyDecision(Decision.ALLOW, Reason.PERMITTED, PolicyVersion("v1")),
        clock.now(),
    )
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.audit.append(operation.requested_event())
        work.commit()
    with SqliteUnitOfWork(database) as work:
        assert work.operations.find(principal.id, operation.key) == operation
