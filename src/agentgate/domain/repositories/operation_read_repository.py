from typing import Protocol

from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_inspection import OperationInspection


class OperationReadRepository(Protocol):
    def get(self, operation_id: OperationId) -> OperationInspection | None: ...
