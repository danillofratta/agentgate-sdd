import os
from functools import partial
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentgate.application.ports.demo_api_gateway import DemoApiGateway
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.components import Components
from agentgate.domain.repositories.account_repository import AccountRepository
from agentgate.domain.repositories.audit_read_repository import AuditReadRepository
from agentgate.domain.repositories.operation_read_repository import OperationReadRepository
from agentgate.domain.value_objects.principal import Principal
from agentgate.features.approve_operation.handler import ApproveOperationHandler
from agentgate.features.evaluate_policy.handler import (
    EvaluatePolicyHandler,
)
from agentgate.features.execute_operation.handler import ExecuteOperationHandler
from agentgate.features.get_operation.handler import GetOperationHandler
from agentgate.features.list_accounts.handler import ListAccountsHandler
from agentgate.features.list_audit.handler import ListAuditHandler
from agentgate.features.request_operation.handler import (
    RequestOperationHandler,
)
from agentgate.infrastructure.gateways.local_credential_gateway import LocalCredentialGateway
from agentgate.infrastructure.gateways.local_demo_api_gateway import LocalDemoApiGateway
from agentgate.infrastructure.gateways.local_tool_registry_gateway import LocalToolRegistryGateway
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.persistence.postgres_database import initialize as initialize_postgres
from agentgate.infrastructure.persistence.postgres_unit_of_work import PostgresUnitOfWork
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.repositories.postgres_account_read_repository import (
    PostgresAccountReadRepository,
)
from agentgate.infrastructure.repositories.postgres_audit_read_repository import (
    PostgresAuditReadRepository,
)
from agentgate.infrastructure.repositories.postgres_operation_read_repository import (
    PostgresOperationReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_account_read_repository import (
    SqliteAccountReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_audit_read_repository import (
    SqliteAuditReadRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import (
    SqliteOperationReadRepository,
)
from agentgate.infrastructure.runtime.system_clock import SystemClock
from agentgate.infrastructure.runtime.system_sleeper import SystemSleeper
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.settings import Settings, secret
from agentgate.infrastructure.tools.get_balance_adapter import GetBalanceAdapter
from agentgate.infrastructure.tools.simulate_transfer_adapter import SimulateTransferAdapter


def build_components(settings: Settings | None = None) -> Components:
    configured = settings if settings is not None else Settings.from_environment()
    factory: RequestUnitOfWorkFactory
    operations: OperationReadRepository
    audit: AuditReadRepository
    accounts: AccountRepository
    if configured.database.startswith(("postgresql://", "postgres://")):
        initialize_postgres(
            configured.database,
            seed=local_development() and os.environ.get("AGENTGATE_SEED") == "1",
        )
        factory = partial(PostgresUnitOfWork, configured.database)
        operations = PostgresOperationReadRepository(configured.database)
        audit = PostgresAuditReadRepository(configured.database)
        accounts = PostgresAccountReadRepository(configured.database)
    else:
        initialize(configured.database)
        factory = partial(SqliteUnitOfWork, configured.database)
        operations = SqliteOperationReadRepository(configured.database)
        audit = SqliteAuditReadRepository(configured.database)
        accounts = SqliteAccountReadRepository(configured.database)
    credentials = LocalCredentialGateway(configured)
    clock = SystemClock()
    return Components(
        RequestOperationHandler(
            factory,
            EvaluatePolicyHandler(),
            SystemClock(),
            UuidOperationIdGenerator(),
        ),
        credentials,
        ListAuditHandler(audit),
        GetOperationHandler(operations),
        ApproveOperationHandler(factory, clock),
        ExecuteOperationHandler(
            factory,
            LocalToolRegistryGateway(GetBalanceAdapter(), SimulateTransferAdapter()),
            EvaluatePolicyHandler(),
            clock,
            SystemSleeper(),
            credentials,
        ),
        ListAccountsHandler(accounts),
    )


def local_development() -> bool:
    return os.environ.get("AGENTGATE_LOCAL_DEVELOPMENT") == "1"


def build_demo_gateway() -> DemoApiGateway:
    configured = Settings(secret("AGENTGATE_AGENT_TOKEN"), secret("AGENTGATE_APPROVER_TOKEN"))
    return LocalDemoApiGateway(configured.agent_token, configured.approver_token)


def get_demo_gateway(request: Request) -> DemoApiGateway:
    return cast(DemoApiGateway, request.app.state.demo_gateway)


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


def get_list_accounts_handler(
    components: Annotated[Components, Depends(get_components)],
) -> ListAccountsHandler:
    if components.list_accounts is None:
        raise HTTPException(503, detail="STORAGE_UNAVAILABLE")
    return components.list_accounts
