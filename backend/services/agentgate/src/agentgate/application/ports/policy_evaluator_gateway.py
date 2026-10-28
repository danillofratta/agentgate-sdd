from typing import Protocol

from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot


class PolicyEvaluatorGateway(Protocol):
    def evaluate(self, snapshot: PolicySnapshot) -> PolicyDecision: ...
