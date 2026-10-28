from agentgate.domain.exceptions.invariant_violation import InvariantViolation


class InsufficientFunds(InvariantViolation):
    """The source account cannot fund the transfer."""
