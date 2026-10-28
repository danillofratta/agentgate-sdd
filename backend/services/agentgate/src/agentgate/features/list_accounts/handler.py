from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.domain.enums.role import Role
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.features.list_accounts.query import ListAccountsQuery


class ListAccountsHandler:
    def __init__(self, repository: AccountRepository) -> None:
        self._repository = repository

    def handle(self, query: ListAccountsQuery) -> tuple[AccountFacts, ...]:
        if query.principal.role != Role.APPROVER:
            raise Forbidden
        return self._repository.facts()
