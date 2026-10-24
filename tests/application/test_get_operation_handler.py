from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.not_found import NotFound
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_inspection import OperationInspection
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.get_operation.query import GetOperationQuery
from tests.infrastructure.test_transactional_persistence import operation as operation_fixture

operation = operation_fixture


class ReadOnlyOperationRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.ids = []

    def get(self, operation_id):
        self.ids.append(operation_id)
        return self.snapshot

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected collaborator access: {name}")


@pytest.mark.parametrize("role", [Role.AGENT, Role.APPROVER])
def test_owner_and_approver_use_only_injected_reader(principal, operation, role, monkeypatch):
    import sqlite3

    def forbidden(*args, **kwargs):
        pytest.fail("Handler accessed concrete storage")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    reader = ReadOnlyOperationRepository(OperationInspection(operation))
    caller = (
        principal
        if role == Role.AGENT
        else replace(principal, id=PrincipalId("principal-approver"), role=role)
    )
    # Read ownership does not re-evaluate current tool/account permissions.
    caller = replace(caller, tools=frozenset(), source_accounts=frozenset())
    result = GetOperationHandler(reader).handle(GetOperationQuery(caller, operation.id))
    assert result.operation is operation
    assert result.approval is result.result is None
    assert result.simulation is True
    assert reader.ids == [operation.id]
    with pytest.raises(FrozenInstanceError):
        result.simulation = False


@pytest.mark.parametrize("missing", [False, True])
def test_direct_handler_conceals_other_agent_and_missing_operation(principal, operation, missing):
    reader = ReadOnlyOperationRepository(None if missing else OperationInspection(operation))
    other = replace(principal, id=PrincipalId("principal-other"))
    with pytest.raises(NotFound) as error:
        GetOperationHandler(reader).handle(GetOperationQuery(other, operation.id))
    assert str(error.value) == ""


def test_missing_operation_for_owner(principal, operation):
    with pytest.raises(NotFound):
        GetOperationHandler(ReadOnlyOperationRepository(None)).handle(
            GetOperationQuery(principal, operation.id)
        )


@pytest.mark.parametrize(
    "principal", [None, {"role": "APPROVER"}, SimpleNamespace(role="APPROVER")]
)
def test_query_rejects_client_identity_shapes(principal):
    with pytest.raises(InvariantViolation, match="INVALID_QUERY"):
        GetOperationQuery(principal, OperationId("00000000-0000-4000-8000-000000000001"))


@pytest.mark.parametrize(
    "operation_id", [None, "'; DELETE FROM operations", "00000000-0000-4000-8000-000000000001"]
)
def test_query_requires_validated_id(principal, operation_id):
    with pytest.raises(InvariantViolation, match="INVALID_QUERY"):
        GetOperationQuery(principal, operation_id)


def test_client_role_override_is_not_accepted(principal, operation):
    with pytest.raises(TypeError):
        GetOperationQuery(principal, operation.id, role=Role.APPROVER)
