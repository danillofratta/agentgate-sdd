from dataclasses import dataclass

from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.ports.clock_gateway import ClockGateway


@dataclass(frozen=True)
class ExecutionDeadline:
    clock: ClockGateway
    expires_at: float

    def remaining(self) -> float:
        remaining = self.expires_at - self.clock.monotonic()
        if remaining <= 0:
            raise ExecutionTimedOut
        return remaining
