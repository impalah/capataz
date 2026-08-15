from uuid import UUID, uuid4

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = self._safe_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        with logger.contextualize(correlation_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _safe_request_id(value: str | None) -> str:
        # Client-supplied ids are bound into every log line for the request; only accept a
        # well-formed UUID to prevent log injection/flooding via an arbitrary header value.
        if value:
            try:
                return str(UUID(value))
            except ValueError:
                pass
        return str(uuid4())
