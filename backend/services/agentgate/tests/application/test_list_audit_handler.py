from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.domain.enums.role import Role
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.audit_page import AuditPage
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.list_audit.query import ListAuditQuery


class ReadOnlyAuditRepository:
    def __init__(self):
        self.pages = []

    def list(self, page):
        self.pages.append(page)
        return ()

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected repository access: {name}")


def approver(principal):
    return replace(principal, id=PrincipalId("principal-approver"), role=Role.APPROVER)


def test_direct_handler_denies_agent_before_repository_access(principal):
    repository = ReadOnlyAuditRepository()
    handler = ListAuditHandler(repository)
    with pytest.raises(Forbidden):
        handler.handle(ListAuditQuery(principal))
    assert repository.pages == []


def test_approver_uses_only_read_contract_and_default_page(principal):
    repository = ReadOnlyAuditRepository()
    result = ListAuditHandler(repository).handle(ListAuditQuery(approver(principal)))
    assert repository.pages == [AuditPage(0, 50)]
    assert result.events == ()
    assert result.next_after == 0
    with pytest.raises(FrozenInstanceError):
        result.next_after = 1


@pytest.mark.parametrize("after,limit", [(0, 1), (5, 100), (2**63 - 1, 50)])
def test_handler_passes_bounded_cursor_and_preserves_empty_cursor(principal, after, limit):
    repository = ReadOnlyAuditRepository()
    result = ListAuditHandler(repository).handle(ListAuditQuery(approver(principal), after, limit))
    assert repository.pages == [AuditPage(after, limit)]
    assert result.next_after == after


@pytest.mark.parametrize("limit", [0, -1, 101, True, False, 1.5, "50", None])
def test_direct_query_rejects_invalid_limit(principal, limit):
    with pytest.raises(InvariantViolation, match="INVALID_AUDIT_LIMIT"):
        ListAuditQuery(approver(principal), limit=limit)


@pytest.mark.parametrize("after", [-1, 2**63, True, False, 1.5, "0", None, "0; DELETE"])
def test_direct_query_rejects_invalid_cursor(principal, after):
    with pytest.raises(InvariantViolation, match="INVALID_AUDIT_CURSOR"):
        ListAuditQuery(approver(principal), after=after)


@pytest.mark.parametrize(
    "principal", [None, {"role": "APPROVER"}, SimpleNamespace(role="APPROVER")]
)
def test_query_rejects_untrusted_identity_shape(principal):
    with pytest.raises(InvariantViolation, match="INVALID_QUERY"):
        ListAuditQuery(principal)
