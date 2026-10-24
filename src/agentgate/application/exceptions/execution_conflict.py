from agentgate.domain.exceptions.invalid_transition import InvalidTransition


class ExecutionConflict(InvalidTransition):
    """The operation lifecycle does not currently permit execution (HTTP 409)."""
