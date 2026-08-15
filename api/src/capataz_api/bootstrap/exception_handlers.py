"""Global exception handlers: every error response is an RFC 7807 ProblemDetail.

`DomainError` subclasses are the application's own, expected errors (not found,
conflict, ...) and get a capataz-specific `type` URI. `HTTPException` and
`RequestValidationError` are FastAPI/Starlette's own signals (e.g. a 503 raised
by a health check, or a malformed request body) and get an RFC 7231/7807
section URI instead. Anything else is an unexpected bug: it is logged with a
stack trace and turned into an opaque 500 that never leaks internals.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from capataz_api.adapters.inbound.schemas import ProblemDetail, ValidationErrorDetail
from capataz_api.domain.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)

_PROBLEM_MEDIA_TYPE = "application/problem+json"

_DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    AuthorizationError: 403,
    ConflictError: 409,
    ValidationError: 422,
    ExternalServiceError: 502,
    ConfigurationError: 500,
}


def _domain_error_status(exc: DomainError) -> int:
    for error_type, status in _DOMAIN_ERROR_STATUS.items():
        if isinstance(exc, error_type):
            return status
    return 400


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        media_type=_PROBLEM_MEDIA_TYPE,
        content=problem.model_dump(exclude_none=True),
    )


def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status = _domain_error_status(exc)
    logger.bind(status_code=status, path=request.url.path, method=request.method).warning(
        f"{exc.__class__.__name__}: {exc}"
    )
    problem = ProblemDetail(
        type=f"https://capataz.local/problems/{exc.__class__.__name__.lower()}",
        title=exc.__class__.__name__.replace("Error", " error"),
        status=status,
        detail=str(exc),
        instance=request.url.path,
        correlation_id=getattr(request.state, "request_id", None),
    )
    return _problem_response(problem)


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.bind(status_code=exc.status_code, path=request.url.path, method=request.method).warning(
        f"HTTPException: {exc.status_code} - {exc.detail}"
    )
    problem = ProblemDetail(
        title="An error occurred",
        status=exc.status_code,
        detail=str(exc.detail),
        instance=request.url.path,
        correlation_id=getattr(request.state, "request_id", None),
    )
    return _problem_response(problem)


def _json_safe_input(value: object) -> object:
    # A malformed (non-JSON) body surfaces here as raw bytes, which stdlib json.dumps (used by
    # JSONResponse) cannot serialize — decode it to text instead of crashing the error handler.
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.bind(path=request.url.path, method=request.method).warning(
        f"Validation error: {len(exc.errors())} error(s)"
    )
    errors = [
        ValidationErrorDetail(
            type=error["type"],
            loc=tuple(str(item) for item in error["loc"]),
            msg=error["msg"],
            input=_json_safe_input(error.get("input")),
            ctx=(
                {key: str(value) for key, value in error["ctx"].items()}
                if error.get("ctx")
                else None
            ),
            url=error.get("url"),
        )
        for error in exc.errors()
    ]
    problem = ProblemDetail(
        title="Validation Error",
        status=422,
        detail=f"One or more validation errors occurred ({len(errors)} error(s)).",
        instance=request.url.path,
        errors=errors,
        correlation_id=getattr(request.state, "request_id", None),
    )
    return _problem_response(problem)


def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.bind(path=request.url.path, method=request.method).exception(
        f"Unhandled {type(exc).__name__}"
    )
    problem = ProblemDetail(
        title="Internal Server Error",
        status=500,
        detail="An unexpected error occurred. Please try again later.",
        instance=request.url.path,
        correlation_id=getattr(request.state, "request_id", None),
    )
    return _problem_response(problem)


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """Catches exceptions that escape routing before Starlette's own ServerErrorMiddleware does.

    `add_exception_handler(Exception, ...)` alone is not enough: Starlette wires a bare-`Exception`
    handler into `ServerErrorMiddleware`, which sits *outside* every middleware added via
    `app.add_middleware` (including CORSMiddleware) — so a 500 built that way reaches the browser
    with no `Access-Control-Allow-Origin` header and shows up as an opaque network error instead of
    the sanitized ProblemDetail body every other error path returns. Catching here, *inside*
    CORSMiddleware (see bootstrap/factory.py for the required add_middleware ordering), avoids that.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:  # deliberate last-resort catch-all, see class docstring
            return general_exception_handler(request, exc)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, general_exception_handler)
