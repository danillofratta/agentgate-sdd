from dataclasses import dataclass

from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot


@dataclass(frozen=True)
class EvaluatePolicyQuery:
    snapshot: PolicySnapshot
