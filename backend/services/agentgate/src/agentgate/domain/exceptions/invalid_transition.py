from agentgate.domain.exceptions.invariant_violation import InvariantViolation


class InvalidTransition(InvariantViolation):
    """The current lifecycle state or supplied time forbids a transition."""
