from fastapi import FastAPI

from agentgate.components import Components
from agentgate.dependencies import build_components
from agentgate.features.approve_operation.endpoint import router as approve_operation_router
from agentgate.features.execute_operation.endpoint import router as execute_operation_router
from agentgate.features.get_operation.endpoint import router as get_operation_router
from agentgate.features.list_audit.endpoint import router as list_audit_router
from agentgate.features.request_operation.endpoint import router as request_operation_router
from agentgate.transport.configure import configure_http


def create_app(components: Components | None = None) -> FastAPI:
    application = FastAPI(
        title="AgentGate", debug=False, docs_url=None, redoc_url=None, openapi_url=None
    )
    application.state.components = components if components is not None else build_components()
    configure_http(application)
    application.include_router(request_operation_router)
    application.include_router(list_audit_router)
    application.include_router(get_operation_router)
    application.include_router(approve_operation_router)
    application.include_router(execute_operation_router)
    return application
