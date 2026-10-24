from dataclasses import dataclass

from agentgate.application.ports.credential_gateway import CredentialGateway
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)


@dataclass(frozen=True)
class Components:
    request_operation: RequestOperationHandler
    credentials: CredentialGateway
