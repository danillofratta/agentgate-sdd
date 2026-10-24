from dataclasses import dataclass

from agentgate.application.ports.credential_gateway import CredentialGateway
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)


@dataclass(frozen=True)
class Components:
    request_operation: RequestOperationHandler
    credentials: CredentialGateway
    list_audit: ListAuditHandler
    get_operation: GetOperationHandler
    approve_operation: ApproveOperationHandler
    execute_operation: ExecuteOperationHandler
