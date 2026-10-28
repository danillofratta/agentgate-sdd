from agentgate.domain.exceptions.invariant_violation import InvariantViolation


class ApprovalBindingMismatch(InvariantViolation):
    """Approval does not authorize this exact operation and policy version."""
