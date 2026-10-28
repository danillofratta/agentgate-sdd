from dataclasses import dataclass

from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.principal import Principal


@dataclass(frozen=True)
class PolicySnapshot:
    principal: Principal
    request: OperationRequest
    accounts: tuple[AccountFacts, ...]
