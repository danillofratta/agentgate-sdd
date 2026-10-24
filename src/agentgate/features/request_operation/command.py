from dataclasses import dataclass

from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class RequestOperationCommand:
    principal: Principal
    key: IdempotencyKey
    request: OperationRequest

    def __post_init__(self) -> None:
        if not isinstance(self.principal, Principal) or not isinstance(self.key, IdempotencyKey):
            raise InvariantViolation("INVALID_COMMAND")
        if not isinstance(self.request, OperationRequest):
            raise InvariantViolation("INVALID_COMMAND")
