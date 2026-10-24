import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.dependencies import build_components
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.features.request_operation.command import (
    RequestOperationCommand,
)
from agentgate.infrastructure.gateways.local_credential_gateway import LocalCredentialGateway
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.security.settings import Settings
from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN
from tests.domain.test_request_values import transfer


def test_concurrent_submissions_have_one_atomic_record(settings, principal):
    handler = build_components(settings).request_operation
    command = RequestOperationCommand(principal, IdempotencyKey("same"), transfer())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: handler.handle(command), range(2)))
    assert sum(result.created for result in results) == 1
    assert results[0].operation == results[1].operation
    with sqlite3.connect(settings.database) as connection:
        for table in ("operations", "approvals", "audit_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_principal_scoped_keys(settings, principal):
    handler = build_components(settings).request_operation
    first = handler.handle(RequestOperationCommand(principal, IdempotencyKey("same"), transfer()))
    other = replace(principal, id=PrincipalId("principal-other"))
    second = handler.handle(RequestOperationCommand(other, IdempotencyKey("same"), transfer()))
    assert first.operation.id != second.operation.id


def test_reseeding_does_not_reset_balance(database):
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE accounts SET balance_cents=50 WHERE id='acct-alice'")
    initialize(database, seed=True)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT balance_cents FROM accounts WHERE id='acct-alice'"
            ).fetchone()[0]
            == 50
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE accounts SET balance_cents=-1")


def test_unknown_schema_fails_closed(database):
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(StorageUnavailable):
        initialize(database)


def test_explicit_rollback_and_reopen(database, principal, clock):
    from agentgate.domain.entities.operation import Operation
    from agentgate.domain.value_objects.decision import Decision
    from agentgate.domain.value_objects.operation_id import OperationId
    from agentgate.domain.value_objects.policy_decision import PolicyDecision
    from agentgate.domain.value_objects.policy_version import PolicyVersion
    from agentgate.domain.value_objects.reason import Reason

    operation = Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("one"),
        transfer(),
        PolicyDecision(Decision.DENY, Reason.POLICY_UNCERTAIN, PolicyVersion("v1")),
        clock.now(),
    )
    with SqliteUnitOfWork(database) as work:
        work.operations.add(operation)
    with SqliteUnitOfWork(database) as reopened:
        assert reopened.operations.find(principal.id, operation.key) is None


@pytest.mark.parametrize(
    "agent,approver",
    [
        ("", APPROVER_TOKEN),
        ("short", APPROVER_TOKEN),
        (AGENT_TOKEN, AGENT_TOKEN),
        ("sample-A6b9C2d5E8f1G4h7J0k3L6m9N2p5Q8r1", APPROVER_TOKEN),
        (AGENT_TOKEN, "a" * 64),
    ],
)
def test_unsafe_configuration_has_no_secret_in_error(agent, approver, database):
    with pytest.raises(ValueError) as error:
        Settings(agent, approver, database)
    assert str(error.value) in {"AGENTGATE_AGENT_TOKEN", "AGENTGATE_APPROVER_TOKEN"}


def test_environment_missing_credentials_prevents_startup(monkeypatch):
    monkeypatch.delenv("AGENTGATE_AGENT_TOKEN", raising=False)
    monkeypatch.delenv("AGENTGATE_APPROVER_TOKEN", raising=False)
    with pytest.raises(ValueError, match="AGENTGATE_AGENT_TOKEN"):
        Settings.from_environment()


def test_credential_verifier_does_not_leak(settings):
    verifier = LocalCredentialGateway(settings)
    assert verifier.verify(AGENT_TOKEN).id.value == "principal-agent"
    assert verifier.verify("bad") is None
    assert verifier.verify("é" * 40) is None
    assert AGENT_TOKEN not in repr(settings)
    assert APPROVER_TOKEN not in repr(settings)


def test_network_and_subprocess_guards():
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="forbidden"):
            connection.connect(("127.0.0.1", 1))
    with pytest.raises(AssertionError, match="forbidden"):
        subprocess.run(["not-a-real-tool"], check=True)
