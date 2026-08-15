"""Unit tests for bootstrap/factory.py and bootstrap/routing.py.

create_app() itself never touches the DB/Redis/secrets (that only happens inside the
`lifespan` context manager, which only runs when the app actually starts serving), so these
tests can call it directly and inspect the resulting FastAPI app's routes/middleware.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from capataz_api.bootstrap.factory import create_app
from capataz_api.core.settings import Settings


def test_create_app_registers_every_router() -> None:
    # app.routes internals vary across FastAPI versions (routers may be mounted lazily as
    # opaque wrapper objects); the OpenAPI schema is the stable, public view of what's
    # actually reachable, so assert against that instead.
    app = create_app(Settings())
    paths = set(app.openapi()["paths"].keys())
    assert "/health/live" in paths
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/services" in paths
    assert "/api/v1/services/{service_id}/actions" in paths
    assert "/api/v1/executions" in paths
    assert "/api/v1/catalog/import" in paths
    assert "/api/v1/audit-events" in paths


def test_create_app_uses_openapi_url_and_title() -> None:
    app = create_app(Settings())
    assert app.title == "Capataz API"
    assert app.openapi_url == "/api/v1/openapi.json"


def test_create_app_configures_cors_from_settings() -> None:
    app = create_app(Settings(cors_origins="https://a.home.arpa,https://b.home.arpa"))
    cors_middlewares = [mw for mw in app.user_middleware if mw.cls is CORSMiddleware]
    assert len(cors_middlewares) == 1
    options = cors_middlewares[0].kwargs
    assert options["allow_origins"] == ["https://a.home.arpa", "https://b.home.arpa"]
    assert options["allow_credentials"] is True
    assert "Authorization" in options["allow_headers"]
    assert "X-Request-ID" in options["expose_headers"]


def test_create_app_falls_back_to_get_settings_when_none_given(monkeypatch) -> None:
    sentinel = Settings()
    monkeypatch.setattr("capataz_api.bootstrap.factory.get_settings", lambda: sentinel)
    app = create_app(None)
    assert app.state.configured_settings is sentinel


def test_unhandled_exception_still_gets_cors_headers() -> None:
    # Regression test for UnhandledExceptionMiddleware (see its docstring): Starlette wires a
    # bare-Exception handler into its own ServerErrorMiddleware, which sits *outside* every
    # app.add_middleware() layer including CORSMiddleware — without the extra middleware, a real
    # 500 would reach the browser with no Access-Control-Allow-Origin header at all.
    app = create_app(Settings(cors_origins="https://a.home.arpa"))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    client = TestClient(app)
    response = client.get("/boom", headers={"Origin": "https://a.home.arpa"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "https://a.home.arpa"
