from agentgate.application.exceptions.not_found import NotFound
from agentgate.domain.enums.role import Role
from agentgate.domain.repositories.operation_read_repository import OperationReadRepository
from agentgate.features.get_operation.query import GetOperationQuery
from agentgate.features.get_operation.result import GetOperationResult


class GetOperationHandler:
    def __init__(self, repository: OperationReadRepository) -> None:
        self._repository = repository

    def handle(self, query: GetOperationQuery) -> GetOperationResult:
        snapshot = self._repository.get(query.operation_id)
        if snapshot is None or not (
            query.principal.role == Role.APPROVER
            or (
                query.principal.role == Role.AGENT
                and query.principal.id == snapshot.operation.principal_id
            )
        ):
            raise NotFound
        return GetOperationResult(snapshot.operation, snapshot.approval, snapshot.result)
