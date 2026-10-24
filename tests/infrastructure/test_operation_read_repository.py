import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.approval_decision import ApprovalDecision
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.features.approve_operation.command import ApproveOperationCommand
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.get_operation.query import GetOperationQuery
from agentgate.infrastructure.persistence.database import LEGACY_SCHEMA, initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture
from tests.infrastructure.test_transactional_persistence import (
    persist,
    snapshot,
)

operation = operation_fixture


@pytest.mark.parametrize("elapsed", [300, 301, 86400])
@pytest.mark.parametrize("granted", [False, True])
def test_repeated_reads_after_expiry_leave_database_and_audit_unchanged(
    database, principal, operation, clock, monkeypatch, elapsed, granted
):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    if granted:
        approver = replace(principal, id=PrincipalId("principal-human"), role=Role.APPROVER)
        result = ApproveOperationHandler(lambda: SqliteUnitOfWork(database), clock).handle(
            ApproveOperationCommand(approver, operation.id, ApprovalDecision.APPROVE)
        )
        operation = result.approval.operation
    before = snapshot(database)
    before_bytes = Path(database).read_bytes()
    clock.value += timedelta(seconds=elapsed)
    real_connect = sqlite3.connect
    statements = []
    connections = []

    def read_only_connect(*args, **kwargs):
        assert kwargs["uri"] is True
        assert args[0].endswith("?mode=ro")
        connection = real_connect(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM audit_events")
        connection.set_trace_callback(statements.append)
        connections.append(connection)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", read_only_connect)
        handler = GetOperationHandler(SqliteOperationReadRepository(database))
        for _ in range(3):
            result = handler.handle(GetOperationQuery(principal, operation.id))
            assert result.operation == operation
            assert result.approval.state == (
                ApprovalState.GRANTED if granted else ApprovalState.PENDING
            )
            assert result.approval.expires_at <= clock.now()
            assert result.result is None
            with pytest.raises(NotFound):
                handler.handle(
                    GetOperationQuery(
                        replace(principal, id=PrincipalId("principal-other")), operation.id
                    )
                )
    assert all(sql.startswith(("PRAGMA query_only=ON", "BEGIN", "SELECT")) for sql in statements)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert snapshot(database) == before
    assert Path(database).read_bytes() == before_bytes


@pytest.mark.parametrize("balance", [True, False])
def test_persisted_results_survive_reopen_without_recomputation(
    database, principal, operation, balance
):
    operation = replace(
        operation, policy=PolicyDecision(Decision.ALLOW, Reason.PERMITTED, operation.policy.version)
    )
    payload = {
        "source_account_id": "acct-alice",
        "destination_account_id": "acct-bob",
        "amount_cents": operation.request.arguments.amount.cents,
        "currency": "USD",
    }
    expected = operation.request.arguments
    if balance:
        operation = replace(
            operation, request=OperationRequest(BalanceArguments(AccountId("acct-alice")))
        )
        payload = {"account_id": "acct-alice", "balance_cents": 123, "currency": "USD"}
        expected = BalanceResult(AccountId("acct-alice"), 123)
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.audit.append(operation.requested_event())
        work.commit()
    # Seed durable execution evidence, without implementing an execution command.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE operations SET state='SUCCEEDED', result_json=?", (json.dumps(payload),)
        )
        connection.execute("UPDATE accounts SET balance_cents=999")
    initialize(database)
    before = snapshot(database)
    for _ in range(3):
        result = GetOperationHandler(SqliteOperationReadRepository(database)).handle(
            GetOperationQuery(principal, operation.id)
        )
        assert result.operation.state == OperationState.SUCCEEDED
        assert result.operation.policy == operation.policy
        assert result.result == expected
        assert result.approval is None
    assert snapshot(database) == before


def test_missing_operation_and_database_are_read_only(database, tmp_path):
    operation_id = OperationId("00000000-0000-4000-8000-000000000001")
    assert SqliteOperationReadRepository(database).get(operation_id) is None
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(StorageUnavailable) as error:
        SqliteOperationReadRepository(str(missing)).get(operation_id)
    assert str(error.value) == ""
    assert not missing.exists()


def test_legacy_schema_migrates_atomically_and_reopens(tmp_path, operation):
    path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as connection:
        for statement in LEGACY_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
    with SqliteUnitOfWork(path) as work:
        persist(work, operation)
        work.commit()
    initialize(path)
    before = snapshot(path)
    initialize(path)
    assert snapshot(path) == before
    assert SqliteOperationReadRepository(path).get(operation.id).operation == operation
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT result_json FROM operations").fetchone()[0] is None


@pytest.mark.parametrize(
    "column,value",
    [
        ("state", "UNKNOWN"),
        ("result_json", '{"secret":"sentinel"}'),
        ("result_json", "null"),
        ("result_json", "not-json"),
    ],
)
def test_invalid_stored_inspection_fails_safely(database, operation, column, value):
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        work.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE operations SET {column}=?", (value,))
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        SqliteOperationReadRepository(database).get(operation.id)
    assert str(error.value) == ""
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "null",
        "not-json",
        '{"secret":"sentinel"}',
        '{"account_id":"acct-bob","balance_cents":123,"currency":"USD"}',
        '{"account_id":"acct-alice","balance_cents":true,"currency":"USD"}',
        '{"account_id":"acct-alice","balance_cents":-1,"currency":"USD"}',
        '{"account_id":"acct-alice","balance_cents":123,"currency":"EUR"}',
    ],
)
def test_invalid_persisted_success_result_is_sanitized(database, operation, payload):
    operation = replace(
        operation,
        request=OperationRequest(BalanceArguments(AccountId("acct-alice"))),
        policy=PolicyDecision(Decision.ALLOW, Reason.PERMITTED, operation.policy.version),
    )
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
        work.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE operations SET state='SUCCEEDED', result_json=?", (payload,))
    before = snapshot(database)
    with pytest.raises(StorageUnavailable) as error:
        SqliteOperationReadRepository(database).get(operation.id)
    assert str(error.value) == ""
    assert snapshot(database) == before


def test_reader_does_not_see_uncommitted_operation(database, operation):
    reader = SqliteOperationReadRepository(database)
    with SqliteUnitOfWork(database) as work:
        persist(work, operation)
        assert reader.get(operation.id) is None
        work.commit()
    assert reader.get(operation.id).operation == operation
