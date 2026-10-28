from agentgate.domain.exceptions.invariant_violation import InvariantViolation


class ApproverRequired(InvariantViolation):
    """A separate trusted approver must make the decision."""
