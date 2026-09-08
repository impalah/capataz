"""FastAPI TestClient tests for routers/health.py (liveness/readiness probes)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from capataz_api.adapters.inbound.routers.health import router
from capataz_api.bootstrap.exception_handlers import register_exception_handlers


class FakeSession:
    async def execute(self, statement: object) -> None:
        return None


class FailingSession:
    async def execute(self, statement: object) -> None:
        raise RuntimeError("db is down")


class FakeRedisWithPing:
    async def ping(self) -> bool:
        return True


class FailingRedis:
    async def ping(self) -> bool:
        raise RuntimeError("redis is down")


def build_app(session_cls: type, redis: object) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    @asynccontextmanager
    async def session_factory():
        yield session_cls()

    app.state.session_factory = session_factory
    app.state.redis = redis
    return app


def test_live_endpoint_always_ok() -> None:
    client = TestClient(build_app(FakeSession, FakeRedisWithPing()))
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ready_endpoint_ok_when_db_and_redis_are_up() -> None:
    client = TestClient(build_app(FakeSession, FakeRedisWithPing()))
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_endpoint_returns_503_when_redis_is_unreachable() -> None:
    client = TestClient(build_app(FakeSession, FailingRedis()))
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Dependencies are not ready"


def test_ready_endpoint_returns_503_when_database_is_unreachable() -> None:
    client = TestClient(build_app(FailingSession, FakeRedisWithPing()))
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Dependencies are not ready"
