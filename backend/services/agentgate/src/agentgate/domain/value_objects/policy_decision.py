from dataclasses import dataclass

from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.reason import Reason
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.policy_version import PolicyVersion


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: Reason
    version: PolicyVersion

    def __post_init__(self) -> None:
        if not isinstance(self.decision, Decision) or not isinstance(self.reason, Reason):
            raise InvariantViolation("INVALID_POLICY_DECISION")
        if not isinstance(self.version, PolicyVersion):
            raise InvariantViolation("INVALID_POLICY_VERSION")
        if self.decision == Decision.ALLOW and self.reason not in {
            Reason.PERMITTED,
            Reason.HUMAN_APPROVED,
        }:
            raise InvariantViolation("INVALID_POLICY_DECISION")
        if self.decision == Decision.REQUIRE_APPROVAL and self.reason != Reason.APPROVAL_REQUIRED:
            raise InvariantViolation("INVALID_POLICY_DECISION")
        if self.decision == Decision.DENY and self.reason in {
            Reason.PERMITTED,
            Reason.APPROVAL_REQUIRED,
            Reason.HUMAN_APPROVED,
        }:
            raise InvariantViolation("INVALID_POLICY_DECISION")
