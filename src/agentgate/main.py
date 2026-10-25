from fastapi import FastAPI

from agentgate.components import Components
from agentgate.dependencies import build_components, local_development
from agentgate.features.approve_operation.endpoint import router as approve_operation_router
from agentgate.features.execute_operation.endpoint import router as execute_operation_router
from agentgate.features.get_operation.endpoint import router as get_operation_router
from agentgate.features.list_accounts.endpoint import router as list_accounts_router
from agentgate.features.list_audit.endpoint import router as list_audit_router
from agentgate.features.request_operation.endpoint import router as request_operation_router
from agentgate.transport.configure import configure_http


def create_app(components: Components | None = None, *, local: bool | None = None) -> FastAPI:
    enabled = local_development() if local is None else local
    application = FastAPI(
        title="AgentGate",
        debug=False,
        docs_url="/docs" if enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if enabled else None,
    )
    application.state.components = components if components is not None else build_components()
    configure_http(application, local=enabled)
    application.include_router(request_operation_router)
    application.include_router(list_audit_router)
    application.include_router(get_operation_router)
    application.include_router(approve_operation_router)
    application.include_router(execute_operation_router)
    if enabled:
        application.include_router(list_accounts_router)
    return application
