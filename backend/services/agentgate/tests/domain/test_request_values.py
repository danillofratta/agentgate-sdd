from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from agentgate.domain.entities.account import Account
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.role import Role
from agentgate.domain.enums.tool import Tool
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.policies.operation_policy import evaluate_policy
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


def transfer(amount=10001):
    return OperationRequest(
        TransferArguments(AccountId("acct-alice"), AccountId("acct-bob"), Money(amount))
    )


@pytest.mark.parametrize("amount", [True, False, 0, -1, 1.0, "100", 2**63])
def test_strict_money_without_http(amount):
    with pytest.raises(InvariantViolation):
        Money(amount)


@pytest.mark.parametrize("identifier", ["acct-alice' OR 1=1", "../acct-alice", "acct-", "acct-a\n"])
def test_strict_account_identifiers(identifier):
    with pytest.raises(InvariantViolation):
        AccountId(identifier)


def test_invariants_do_not_depend_on_api():
    with pytest.raises(InvariantViolation):
        Money(1, "EUR")
    with pytest.raises(InvariantViolation):
        TransferArguments(AccountId("acct-alice"), AccountId("acct-alice"), Money(1))
    with pytest.raises(InvariantViolation):
        TransferArguments("acct-alice", AccountId("acct-bob"), Money(1))
    with pytest.raises(InvariantViolation):
        OperationRequest({"tool": "shell"})
    with pytest.raises(InvariantViolation):
        Account(AccountId("acct-alice"), -1)
    with pytest.raises(InvariantViolation):
        Account(AccountId("acct-alice"), True)
    with pytest.raises(FrozenInstanceError):
        Money(1).cents = 2


@pytest.mark.parametrize("key", ["", "a" * 65, "bad/key", "á", "key\n"])
def test_invalid_idempotency_key(key):
    with pytest.raises(InvariantViolation):
        IdempotencyKey(key)


@pytest.mark.parametrize(
    "amount,expected",
    [
        (1, Decision.ALLOW),
        (10000, Decision.ALLOW),
        (10001, Decision.REQUIRE_APPROVAL),
        (100000, Decision.REQUIRE_APPROVAL),
        (100001, Decision.DENY),
    ],
)
def test_exact_policy_boundaries(principal, amount, expected):
    snapshot = PolicySnapshot(
        principal,
        transfer(amount),
        (
            AccountFacts(AccountId("acct-alice"), 1000000),
            AccountFacts(AccountId("acct-bob"), 1000000),
        ),
    )
    assert evaluate_policy(snapshot).decision == expected
    assert evaluate_policy(snapshot) == evaluate_policy(snapshot)


@pytest.mark.parametrize(
    "tools,sources,accounts,reason",
    [
        (frozenset(), frozenset({AccountId("acct-alice")}), (), Reason.TOOL_NOT_ALLOWED),
        (frozenset(Tool), frozenset(), (), Reason.SOURCE_NOT_ALLOWED),
        (frozenset(Tool), frozenset({AccountId("acct-alice")}), (), Reason.UNKNOWN_ACCOUNT),
        (
            frozenset(Tool),
            frozenset({AccountId("acct-alice")}),
            (AccountFacts(AccountId("acct-alice"), 0), AccountFacts(AccountId("acct-bob"), 10)),
            Reason.INSUFFICIENT_FUNDS,
        ),
    ],
)
def test_missing_or_disallowed_facts_deny(tools, sources, accounts, reason):
    principal = Principal(PrincipalId("principal-test"), Role.AGENT, tools, sources)
    result = evaluate_policy(PolicySnapshot(principal, transfer(1), accounts))
    assert result.decision == Decision.DENY
    assert result.reason == reason


def test_balance_ownership(principal):
    result = evaluate_policy(
        PolicySnapshot(
            principal,
            OperationRequest(BalanceArguments(AccountId("acct-bob"))),
            (AccountFacts(AccountId("acct-bob"), 100),),
        )
    )
    assert result.reason == Reason.SOURCE_NOT_ALLOWED


def test_immutable_pending_approval_is_bound_to_operation(principal, clock):
    policy = PolicyDecision(
        Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED, PolicyVersion("v1")
    )
    operation = Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("one"),
        transfer(),
        policy,
        clock.now(),
    )
    approval = Approval(operation)
    assert operation.state == OperationState.PENDING_APPROVAL
    assert approval.expires_at == clock.now() + timedelta(seconds=300)
    assert approval.operation.request.fingerprint == operation.request.fingerprint
    with pytest.raises(FrozenInstanceError):
        operation.request = transfer(2)
    with pytest.raises(InvariantViolation):
        Operation(
            operation.id,
            principal.id,
            operation.key,
            operation.request,
            policy,
            datetime(2026, 1, 1),
        )
    assert operation.created_at.tzinfo == UTC


def test_approval_cannot_be_created_for_allow(principal, clock):
    operation = Operation(
        OperationId("00000000-0000-4000-8000-000000000001"),
        principal.id,
        IdempotencyKey("one"),
        transfer(1),
        PolicyDecision(Decision.ALLOW, Reason.PERMITTED, PolicyVersion("v1")),
        clock.now(),
    )
    with pytest.raises(InvariantViolation):
        Approval(operation)
