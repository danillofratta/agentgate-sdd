"""Persisted/public string contracts frozen before the monorepo relocation."""

import json

import pytest

from agentgate.domain.enums.approval_decision import ApprovalDecision
from agentgate.domain.enums.approval_state import ApprovalState
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.role import Role
from agentgate.domain.enums.tool import Tool


@pytest.mark.parametrize(
    "enum_type,values",
    [
        (Role, ["AGENT", "APPROVER"]),
        (Tool, ["get_balance", "simulate_transfer"]),
        (Decision, ["ALLOW", "DENY", "REQUIRE_APPROVAL"]),
        (ApprovalDecision, ["APPROVE", "REJECT"]),
        (ApprovalState, ["PENDING", "GRANTED", "REJECTED", "EXPIRED", "CONSUMED"]),
        (
            OperationState,
            [
                "DENIED",
                "READY",
                "PENDING_APPROVAL",
                "SUCCEEDED",
                "REJECTED",
                "EXPIRED",
                "FAILED",
                "TIMED_OUT",
            ],
        ),
        (
            Reason,
            [
                "HUMAN_APPROVED",
                "PERMITTED",
                "APPROVAL_REQUIRED",
                "LIMIT_EXCEEDED",
                "TOOL_NOT_ALLOWED",
                "SOURCE_NOT_ALLOWED",
                "UNKNOWN_ACCOUNT",
                "INSUFFICIENT_FUNDS",
                "POLICY_UNCERTAIN",
            ],
        ),
    ],
)
def test_preexisting_persistence_and_json_values_keep_singleton_identity(enum_type, values):
    assert list(enum_type) == [enum_type(value) for value in values]
    assert json.loads(json.dumps(list(enum_type))) == values
    for value in values:
        member = enum_type(value)
        assert enum_type(json.loads(json.dumps(member))) is member
        assert str(member) == value
