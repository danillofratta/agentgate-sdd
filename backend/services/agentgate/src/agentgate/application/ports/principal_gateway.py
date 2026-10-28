from typing import Protocol

from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId


class PrincipalGateway(Protocol):
    def get_principal(self, principal_id: PrincipalId) -> Principal | None: ...
