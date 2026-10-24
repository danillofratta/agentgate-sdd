from typing import Protocol

from agentgate.domain.value_objects.principal import Principal


class CredentialGateway(Protocol):
    def verify(self, token: str) -> Principal | None: ...
