from dataclasses import replace

import pytest

from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from tests.domain.test_entity_invariants import operation as operation_fixture

operation = operation_fixture


@pytest.mark.parametrize("approved", [False, True])
def test_execution_authorization_preserves_original_policy(operation, approved):
    if approved:
        operation = operation.transition(OperationState.READY)
    else:
        operation = replace(
            operation,
            policy=PolicyDecision(Decision.ALLOW, Reason.PERMITTED, operation.policy.version),
        )
    authorization = PolicyDecision(
        Decision.ALLOW,
        Reason.HUMAN_APPROVED if approved else Reason.PERMITTED,
        operation.policy.version,
    )
    authorized = operation.authorize_execution(authorization)
    assert authorized.policy == operation.policy
    assert authorized.execution_authorization == authorization
    assert operation.execution_authorization is None
    with pytest.raises(InvalidTransition):
        authorized.authorize_execution(authorization)
    with pytest.raises(InvalidTransition):
        operation.authorize_execution(replace(authorization, version=PolicyVersion("v2")))
    with pytest.raises(InvalidTransition):
        operation.authorize_execution(
            replace(authorization, reason=Reason.PERMITTED if approved else Reason.HUMAN_APPROVED)
        )
