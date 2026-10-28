from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agentgate.application.exceptions.agent_unavailable import AgentUnavailable
from agentgate.dependencies import get_chat_handler
from agentgate.features.chat_turn.command import ChatTurnCommand
from agentgate.features.chat_turn.handler import ChatTurnHandler
from agentgate.features.chat_turn.models import ChatBody

router = APIRouter()
Handler = Annotated[ChatTurnHandler | None, Depends(get_chat_handler)]


@router.get("/lab/chat/status")
def status(handler: Handler) -> JSONResponse:
    return JSONResponse(
        {
            "available": handler is not None,
            "simulation": True,
            "message": "Provider configured; tool capability is checked on first turn."
            if handler
            else (
                "AI chat is disabled. Configure a server-side provider key and model. "
                "The manual lab is available."
            ),
        }
    )


@router.post("/lab/chat/turn")
async def turn(body: ChatBody, request: Request, handler: Handler) -> JSONResponse:
    if handler is None:
        return JSONResponse({"error": "PROVIDER_NOT_CONFIGURED"}, status_code=503)
    try:
        result = await handler.handle(
            ChatTurnCommand(
                request.cookies["lab_session"],
                body.message,
                body.action,
                body.operation_id,
            )
        )
    except AgentUnavailable:
        return JSONResponse({"error": "CHAT_BUSY_OR_FULL"}, status_code=503)
    return JSONResponse(asdict(result))
