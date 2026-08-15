"""Unit tests for infrastructure/observability/correlation.py."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from capataz_api.infrastructure.observability import CorrelationIdMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    return app


client = TestClient(build_app())


def test_generates_a_request_id_when_none_supplied() -> None:
    response = client.get("/echo")
    assert response.status_code == 200
    request_id = response.json()["request_id"]
    UUID(request_id)  # does not raise
    assert response.headers["X-Request-ID"] == request_id


def test_propagates_a_well_formed_client_supplied_request_id() -> None:
    supplied = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    response = client.get("/echo", headers={"X-Request-ID": supplied})
    assert response.json()["request_id"] == supplied
    assert response.headers["X-Request-ID"] == supplied


def test_rejects_a_malformed_client_supplied_request_id_and_generates_a_fresh_one() -> None:
    response = client.get("/echo", headers={"X-Request-ID": "not-a-uuid"})
    request_id = response.json()["request_id"]
    assert request_id != "not-a-uuid"
    UUID(request_id)  # does not raise


def test_response_header_is_present_when_route_raises_a_handled_exception() -> None:
    # Starlette's ExceptionMiddleware sits *inside* user middleware, so only exceptions with a
    # registered handler turn into a response call_next() can return; an exception with no
    # handler at all propagates straight to ServerErrorMiddleware, bypassing this middleware's
    # header-setting line entirely (out of scope here — it's the register_exception_handlers'
    # general_exception_handler that guarantees full coverage in the real app, see
    # bootstrap/exception_handlers.py).
    from starlette.responses import PlainTextResponse

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(ValueError)
    async def handle_value_error(request: object, exc: ValueError) -> PlainTextResponse:
        return PlainTextResponse("boom", status_code=500)

    @app.get("/boom")
    async def boom() -> None:
        raise ValueError("boom")

    boom_client = TestClient(app, raise_server_exceptions=False)
    response = boom_client.get("/boom")
    assert response.status_code == 500
    assert "X-Request-ID" in response.headers
