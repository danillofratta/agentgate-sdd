from typing import TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.transport.body_limit import BodyLimit
from agentgate.transport.sanitized_errors import SanitizedErrors

E = TypeVar("E", bound=Exception)


def configure_http(application: FastAPI) -> None:
    """Install shared transport safeguards without declaring feature endpoints."""
    application.add_middleware(BodyLimit)
    application.add_middleware(SanitizedErrors)

    def register_error(exception: type[E], code: str, status: int) -> None:
        async def sanitized_error(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"error": code}, status_code=status)

        application.add_exception_handler(exception, sanitized_error)

    register_error(RequestValidationError, "INVALID_INPUT", 422)
    register_error(InvariantViolation, "INVALID_INPUT", 422)
    register_error(Forbidden, "FORBIDDEN", 403)
    register_error(NotFound, "NOT_FOUND", 404)
    register_error(IdempotencyConflict, "IDEMPOTENCY_CONFLICT", 409)
    register_error(StorageUnavailable, "STORAGE_UNAVAILABLE", 503)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": "UNAUTHENTICATED"}, status_code=exc.status_code, headers=exc.headers
        )
