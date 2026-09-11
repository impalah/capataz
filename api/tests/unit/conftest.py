"""Shared fixtures for router-level (FastAPI TestClient) unit tests.

These build a FastAPI app directly from the same `bootstrap.routing`/`bootstrap.exception_handlers`
wiring used in production, but override `adapters.inbound.routers.deps.repo_dependency` with the
in-memory repository double from fakes.py instead of a real SQLAlchemy session — fast and DB-free
while still exercising the real routers, application-layer use cases, RBAC and RFC 7807 errors.
"""

from __future__ import annotations

from pathlib import Path

from fakes import (
    TEST_SUFFIXES,
    FakeConnectorFactory,
    FakeQueue,
    InMemoryServiceRepository,
    make_cipher,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capataz_api.adapters.inbound.auth import DevMockIdentityProvider
from capataz_api.adapters.inbound.routers.deps import repo_dependency
from capataz_api.application.services import CatalogContext, StatusService
from capataz_api.bootstrap.exception_handlers import register_exception_handlers
from capataz_api.bootstrap.routing import register_routes
from capataz_api.infrastructure.observability import CorrelationIdMiddleware
from capataz_api.infrastructure.resources import FileSystemResourceSourceLoader


class FakeSettings:
    health_suffixes = TEST_SUFFIXES


def build_app(
    repo: InMemoryServiceRepository,
    queue: FakeQueue | None = None,
    factory: FakeConnectorFactory | None = None,
) -> FastAPI:
    """A minimal app wired the same way create_app() wires it, minus the real lifespan."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_routes(app)
    register_exception_handlers(app)
    cipher = make_cipher()
    app.state.identity_provider = DevMockIdentityProvider()
    app.state.resource_cipher = cipher
    app.state.status_service = StatusService(factory or FakeConnectorFactory())
    app.state.catalog_context = CatalogContext(
        cipher=cipher,
        # No resource files/env in router tests: only inline sources can load.
        loader=FileSystemResourceSourceLoader(Path("/nonexistent-capataz-resources"), environ={}),
        inline_permitted=True,
        allowed_suffixes=TEST_SUFFIXES,
    )
    app.state.queue = queue or FakeQueue()
    app.state.settings = FakeSettings()

    async def fake_repo_dependency():
        yield repo

    app.dependency_overrides[repo_dependency] = fake_repo_dependency
    return app


def dev_headers(groups: str = "", user: str = "tester") -> dict[str, str]:
    headers = {"X-Dev-User": user}
    if groups:
        headers["X-Dev-Groups"] = groups
    return headers


VIEWER = dev_headers("capataz-viewer")
OPERATOR = dev_headers("capataz-operator")
ADMIN = dev_headers("capataz-admin")
NONE_ROLE = dev_headers("")


def client_for(
    repo: InMemoryServiceRepository,
    queue: FakeQueue | None = None,
    factory: FakeConnectorFactory | None = None,
) -> TestClient:
    return TestClient(build_app(repo, queue, factory))
