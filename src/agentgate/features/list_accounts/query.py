from dataclasses import dataclass

from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class ListAccountsQuery:
    principal: Principal
