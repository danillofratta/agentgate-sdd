from agentgate.domain.policies.operation_policy import evaluate_policy
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.features.evaluate_policy.query import EvaluatePolicyQuery


class EvaluatePolicyHandler:
    def handle(self, query: EvaluatePolicyQuery) -> PolicyDecision:
        return evaluate_policy(query.snapshot)

    def evaluate(self, snapshot: PolicySnapshot) -> PolicyDecision:
        return self.handle(EvaluatePolicyQuery(snapshot))
