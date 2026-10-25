import secrets

from fastapi import FastAPI

from agentgate.application.ports.demo_api_gateway import DemoApiGateway
from agentgate.dependencies import build_chat_handler, build_demo_gateway, local_development
from agentgate.features.chat_turn.endpoint import router as chat_router
from agentgate.features.chat_turn.handler import ChatTurnHandler
from agentgate.features.demo_lab.endpoint import router
from agentgate.transport.configure import configure_http
from agentgate.transport.lab_security import LabSecurity


def create_app(
    gateway: DemoApiGateway | None = None,
    chat_handler: ChatTurnHandler | None = None,
) -> FastAPI:
    if not local_development():
        raise ValueError("AGENTGATE_LOCAL_DEVELOPMENT")
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.state.demo_gateway = gateway if gateway is not None else build_demo_gateway()
    application.state.chat_handler = (
        chat_handler if chat_handler is not None else build_chat_handler()
    )
    application.state.csrf_secret = secrets.token_bytes(32)
    configure_http(application)
    application.add_middleware(LabSecurity, secret=application.state.csrf_secret)
    application.include_router(router)
    application.include_router(chat_router)
    return application
