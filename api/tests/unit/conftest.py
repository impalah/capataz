"""Shared fixtures/test doubles for router-level (FastAPI TestClient) unit tests.

These build a FastAPI app directly from the same `bootstrap.routing`/
`bootstrap.exception_handlers` wiring used in production, but override
`adapters.inbound.routers.deps.repo_dependency` with an in-memory
`ServiceRepository` double instead of a real SQLAlchemy session — this keeps
the tests fast and DB-free while still exercising the real routers, the real
application-layer use cases, RBAC, and the real RFC 7807 error handling.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from capataz_api.adapters.inbound.auth import DevMockIdentityProvider
from capataz_api.adapters.inbound.routers.deps import repo_dependency
from capataz_api.application.services.status import StatusService
from capataz_api.bootstrap.exception_handlers import register_exception_handlers
from capataz_api.bootstrap.routing import register_routes
from capataz_api.domain.entities import ActionDefinition, Execution, Service
from capataz_api.infrastructure.observability import CorrelationIdMiddleware


class InMemoryServiceRepository:
    """Same shape as the double used in test_application_services.py."""

    def __init__(self) -> None:
        self.services: dict[str, Service] = {}
        self.actions: dict[tuple[str, str], ActionDefinition] = {}
        self.executions: dict[UUID, Execution] = {}
        self.audit_events: list[dict[str, Any]] = []
        self.status_cache: dict[str, str] = {}

    async def get_service(self, service_id: str) -> Service | None:
        service = self.services.get(service_id)
        return deepcopy(service) if service is not None else None

    async def list_services(self, **filters: object) -> tuple[list[Service], int]:
        items = [deepcopy(service) for service in self.services.values()]
        if status := filters.get("status"):
            items = [service for service in items if self.status_cache.get(service.id) == status]
        offset = int(filters.get("offset") or 0)
        limit = filters.get("limit")
        page = items[offset : offset + limit] if limit is not None else items[offset:]
        return page, len(items)

    async def update_status_cache(self, service_id: str, status: str) -> None:
        self.status_cache[service_id] = status

    async def upsert_service(self, service: Service, *, enforce_version: bool = False) -> Service:
        existing = self.services.get(service.id)
        if existing is not None and enforce_version and existing.version != service.version:
            from capataz_api.domain.exceptions import ConflictError

            raise ConflictError("The record was modified by another request; reload and retry")
        if existing is not None:
            service.version = existing.version + 1
        self.services[service.id] = service
        return service

    async def delete_service(self, service_id: str) -> bool:
        return self.services.pop(service_id, None) is not None

    async def list_actions(self, service_id: str) -> list[ActionDefinition]:
        return [action for (sid, _key), action in self.actions.items() if sid == service_id]

    async def list_actions_for_services(
        self, service_ids: list[str]
    ) -> dict[str, list[ActionDefinition]]:
        by_service: dict[str, list[ActionDefinition]] = {sid: [] for sid in service_ids}
        for (sid, _key), action in self.actions.items():
            if sid in by_service:
                by_service[sid].append(action)
        return by_service

    async def get_action(self, service_id: str, key: str) -> ActionDefinition | None:
        return self.actions.get((service_id, key))

    async def upsert_action(self, action: ActionDefinition) -> ActionDefinition:
        self.actions[(action.service_id, action.key)] = action
        return action

    async def delete_action(self, service_id: str, key: str) -> bool:
        action = self.actions.get((service_id, key))
        if action is None:
            return False
        active = any(
            execution.action_definition_id == action.id
            and execution.status.value in ("queued", "running")
            for execution in self.executions.values()
        )
        if active:
            return False
        del self.actions[(service_id, key)]
        return True

    async def create_execution(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution

    async def get_execution(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)

    async def list_executions(self, **filters: object) -> tuple[list[Execution], int]:
        items = list(self.executions.values())
        return items, len(items)

    async def events(self, execution_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt-1",
                "sequence": 1,
                "timestamp": "2026-08-14T00:00:00+00:00",
                "level": "info",
                "event_type": "log",
                "message": "hello",
                "data": {},
            }
        ]

    async def append_audit(self, event: dict[str, Any]) -> None:
        # Mirror SqlAlchemyRepository.append_audit's default: metadata is stored as {} when
        # the caller (build_audit_event) omitted it, never left missing (CR-…: AuditEventResponse
        # requires the field).
        self.audit_events.append({"metadata": {}, **event})

    async def list_audit(self, **filters: object) -> tuple[list[dict[str, Any]], int]:
        items = [
            {
                "id": f"audit-{index}",
                "timestamp": "2026-08-14T00:00:00+00:00",
                "outcome": "success",
                **event,
            }
            for index, event in enumerate(self.audit_events)
        ]
        return items, len(items)


class FakeStatusCache:
    def __init__(self, values: dict[str, dict[str, Any]] | None = None) -> None:
        self.values = values or {}

    async def get(self, service_id: str) -> dict[str, Any] | None:
        return self.values.get(service_id)

    async def set(self, service_id: str, value: dict[str, Any], ttl: int) -> None:
        self.values[service_id] = value


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    async def enqueue(self, execution_id: UUID) -> str:
        self.enqueued.append(execution_id)
        return "task-1"


class FakeSettings:
    portainer_url = None
    grafana_url = None
    loki_url = None


def build_app(repo: InMemoryServiceRepository, queue: FakeQueue | None = None) -> FastAPI:
    """A minimal app wired the same way create_app() wires it, minus the real lifespan."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_routes(app)
    register_exception_handlers(app)
    app.state.identity_provider = DevMockIdentityProvider()
    app.state.status_service = StatusService(FakeStatusCache(), None, None, 30)
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


def client_for(repo: InMemoryServiceRepository, queue: FakeQueue | None = None) -> TestClient:
    return TestClient(build_app(repo, queue))
