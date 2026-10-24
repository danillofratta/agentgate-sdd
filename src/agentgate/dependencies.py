from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentgate.components import Components
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.evaluate_policy.handler import (
    EvaluatePolicyHandler,
)
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)
from agentgate.infrastructure.gateways.local_credential_gateway import LocalCredentialGateway
from agentgate.infrastructure.gateways.local_tool_registry_gateway import LocalToolRegistryGateway
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from agentgate.infrastructure.runtime.system_clock import SystemClock
from agentgate.infrastructure.runtime.system_sleeper import SystemSleeper
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.settings import Settings
from agentgate.infrastructure.tools.get_balance_adapter import GetBalanceAdapter
from agentgate.infrastructure.tools.simulate_transfer_adapter import SimulateTransferAdapter


def build_components(settings: Settings | None = None) -> Components:
    configured = settings if settings is not None else Settings.from_environment()
    initialize(configured.database)
    credentials = LocalCredentialGateway(configured)
    clock = SystemClock()
    return Components(
        RequestOperationHandler(
            lambda: SqliteUnitOfWork(configured.database),
            EvaluatePolicyHandler(),
            SystemClock(),
            UuidOperationIdGenerator(),
        ),
        credentials,
        ListAuditHandler(SqliteAuditReadRepository(configured.database)),
        GetOperationHandler(SqliteOperationReadRepository(configured.database)),
        ApproveOperationHandler(lambda: SqliteUnitOfWork(configured.database), clock),
        ExecuteOperationHandler(
            lambda: SqliteUnitOfWork(configured.database),
            LocalToolRegistryGateway(GetBalanceAdapter(), SimulateTransferAdapter()),
            EvaluatePolicyHandler(),
            clock,
            SystemSleeper(),
            credentials,
        ),
    )


def get_components(request: Request) -> Components:
    return cast(Components, request.app.state.components)


def get_handler(
    components: Annotated[Components, Depends(get_components)],
) -> RequestOperationHandler:
    return components.request_operation


def get_principal(
    components: Annotated[Components, Depends(get_components)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> Principal:
    principal = (
        None if credentials is None else components.credentials.verify(credentials.credentials)
    )
    if principal is None:
        raise HTTPException(401, detail="UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"})
    return principal


def get_list_audit_handler(
    components: Annotated[Components, Depends(get_components)],
) -> ListAuditHandler:
    return components.list_audit


def get_get_operation_handler(
    components: Annotated[Components, Depends(get_components)],
) -> GetOperationHandler:
    return components.get_operation


def get_approve_operation_handler(
    components: Annotated[Components, Depends(get_components)],
) -> ApproveOperationHandler:
    return components.approve_operation


def get_execute_operation_handler(
    components: Annotated[Components, Depends(get_components)],
) -> ExecuteOperationHandler:
    return components.execute_operation
