import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from agentgate.application.ports.demo_api_gateway import DemoApiGateway
from agentgate.dependencies import get_demo_gateway
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.operation_id import OperationId

router = APIRouter()
ASSETS = Path(__file__).parent / "static"
Gateway = Annotated[DemoApiGateway, Depends(get_demo_gateway)]


@router.get("/")
def index() -> FileResponse:
    return FileResponse(ASSETS / "index.html")


@router.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(ASSETS / "app.js", media_type="text/javascript")


@router.get("/style.css")
def stylesheet() -> FileResponse:
    return FileResponse(ASSETS / "style.css", media_type="text/css")


@router.get("/lab/session")
def session(request: Request) -> JSONResponse:
    value = secrets.token_urlsafe(32)
    token = hmac.new(request.app.state.csrf_secret, value.encode(), hashlib.sha256).hexdigest()
    response = JSONResponse({"csrf": token, "simulation": True})
    response.set_cookie("lab_session", value, httponly=True, samesite="strict", path="/")
    return response


@router.get("/lab/accounts")
def accounts(gateway: Gateway) -> JSONResponse:
    status, body = gateway.accounts()
    return JSONResponse(body, status_code=status)


@router.get("/lab/audit")
def audit(gateway: Gateway, after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0) -> JSONResponse:
    status, body = gateway.audit(after)
    return JSONResponse(body, status_code=status)


@router.post("/lab/operations")
def submit(
    payload: dict[str, object],
    gateway: Gateway,
    idempotency_key: Annotated[str, Header(pattern=r"\A[A-Za-z0-9_-]{1,64}\z")],
) -> JSONResponse:
    status, body = gateway.submit(payload, idempotency_key)
    return JSONResponse(body, status_code=status)


@router.get("/lab/operations/{id}")
def inspect(id: str, gateway: Gateway) -> JSONResponse:
    status, body = gateway.inspect(OperationId(id).value)
    return JSONResponse(body, status_code=status)


@router.post("/lab/operations/{id}/approval")
def decide(id: str, payload: dict[str, object], gateway: Gateway) -> JSONResponse:
    status, body = gateway.decide(OperationId(id).value, payload)
    return JSONResponse(body, status_code=status)


@router.post("/lab/operations/{id}/execute")
async def run_operation(id: str, request: Request, gateway: Gateway) -> JSONResponse:
    if await request.body():
        raise InvariantViolation("INVALID_INPUT")
    from starlette.concurrency import run_in_threadpool

    status, body = await run_in_threadpool(gateway.run_operation, OperationId(id).value)
    return JSONResponse(body, status_code=status)
