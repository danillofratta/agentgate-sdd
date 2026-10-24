from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable


class ExecutionTimedOut(ExecutionUnavailable):
    """The cooperative execution deadline expired before commit."""
