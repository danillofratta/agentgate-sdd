from typing import Protocol

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.principal_id import PrincipalId


class OperationRepository(Protocol):
    def get(self, operation_id: OperationId) -> Operation | None: ...

    def save_approval_decision(self, operation: Operation) -> None: ...

    def save_approval_expiry(self, operation: Operation) -> None: ...

    def find(self, principal_id: PrincipalId, key: IdempotencyKey) -> Operation | None: ...

    def add(self, operation: Operation) -> None: ...
