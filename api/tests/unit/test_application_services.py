"""Unit tests for the application-layer use cases extracted in Fase 2 of the remediation plan.

Uses a full in-memory ServiceRepository test double (fewer mocks, closer to real repository
behaviour) rather than a partial fake, since these services orchestrate several repository calls.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest

from capataz_api.application.services import (
    ActionApplicationService,
    ExecutionService,
    ServiceApplicationService,
    StatusService,
    export_catalog,
    parse_catalog_yaml,
    upsert_catalog,
)
from capataz_api.domain.entities import ActionDefinition, Execution, Principal, Service
from capataz_api.domain.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from capataz_api.domain.value_objects import ActionType, ExecutionSource, RiskLevel


class InMemoryServiceRepository:
    def __init__(self) -> None:
        self.services: dict[str, Service] = {}
        self.actions: dict[tuple[str, str], ActionDefinition] = {}
        self.executions: dict[UUID, Execution] = {}
        self.audit_events: list[dict[str, Any]] = []
        self.status_cache: dict[str, str] = {}

    async def get_service(self, service_id: str) -> Service | None:
        # A real repository always builds a fresh domain object from persisted storage; return a
        # copy here too, so two independent `get_service` calls can never alias the same instance.
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
        return []

    async def append_audit(self, event: dict[str, Any]) -> None:
        self.audit_events.append(event)

    async def list_audit(self, **filters: object) -> tuple[list[dict[str, Any]], int]:
        return self.audit_events, len(self.audit_events)


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


def make_service(service_id: str, **overrides: Any) -> Service:
    defaults: dict[str, Any] = {
        "id": service_id,
        "name": "Twin Service",
        "group_name": "IA",
        "environment": "homelab",
        "container_selectors": {"containers": [{"name": service_id}]},
    }
    defaults.update(overrides)
    return Service(**defaults)


def make_action(service_id: str, key: str = "restart", **overrides: Any) -> ActionDefinition:
    defaults: dict[str, Any] = {
        "service_id": service_id,
        "key": key,
        "label": "Restart",
        "action_type": ActionType.PORTAINER,
        "risk_level": RiskLevel.OPERATE,
        "config": {"operation": "restart", "target": "selected_containers"},
    }
    defaults.update(overrides)
    return ActionDefinition(**defaults)


ADMIN = Principal("admin", {"capataz-admin"})
OPERATOR = Principal("operator", {"capataz-operator"})


@pytest.mark.asyncio
async def test_list_services_status_filter_attributes_status_by_id_not_dict_equality() -> None:
    """Regression test for CR-016: two services with identical display fields (only id differs)

    must never have their status cross-attributed. CR-063 eliminated this whole bug class:
    status filtering is now a plain repository-level lookup keyed by id (status_cache), not a
    parallel-list index match — there's no way left to attribute the wrong service's status.
    """
    repo = InMemoryServiceRepository()
    await repo.upsert_service(make_service("twin-a"))
    await repo.upsert_service(make_service("twin-b"))
    await repo.update_status_cache("twin-a", "healthy")
    await repo.update_status_cache("twin-b", "down")
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))

    items, total = await service.list_services(
        group_name=None, environment=None, status="healthy", offset=0, limit=20
    )
    assert [item.id for item in items] == ["twin-a"]
    assert total == 1


@pytest.mark.asyncio
async def test_list_services_status_filter_paginates_correctly_across_pages() -> None:
    """CR-063: with more matching services than `limit`, `total` must reflect the full filtered

    count (not just the current page window), and page 2 must return the remaining matches
    without repeating or omitting any — the actual bug CR-016 originally reported.
    """
    repo = InMemoryServiceRepository()
    for index in range(5):
        await repo.upsert_service(make_service(f"svc-{index}"))
        await repo.update_status_cache(f"svc-{index}", "healthy" if index < 3 else "down")
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))

    page1, total1 = await service.list_services(
        group_name=None, environment=None, status="healthy", offset=0, limit=2
    )
    page2, total2 = await service.list_services(
        group_name=None, environment=None, status="healthy", offset=2, limit=2
    )
    assert total1 == 3
    assert total2 == 3
    assert len(page1) == 2
    assert [item.id for item in page2] == ["svc-2"]
    assert {item.id for item in page1} | {item.id for item in page2} == {
        "svc-0",
        "svc-1",
        "svc-2",
    }


@pytest.mark.asyncio
async def test_refresh_status_writes_the_computed_status_to_the_status_cache_column() -> None:
    """CR-063: refresh_status is the only place a service's status is ever computed server-side,

    so it must persist the result to status_cache — otherwise list_services's SQL filter would
    have nothing to match against.
    """
    repo = InMemoryServiceRepository()
    await repo.upsert_service(make_service("svc", maintenance=True))
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))

    await service.refresh_status("svc")

    assert repo.status_cache["svc"] == "maintenance"


@pytest.mark.asyncio
async def test_create_service_rejects_duplicate_id() -> None:
    repo = InMemoryServiceRepository()
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))
    await service.create_service(
        data={"id": "one", "name": "One", "group_name": "G", "environment": "dev"},
        principal=ADMIN,
        request_id="r1",
    )
    with pytest.raises(ConflictError):
        await service.create_service(
            data={"id": "one", "name": "One again", "group_name": "G", "environment": "dev"},
            principal=ADMIN,
            request_id="r2",
        )
    assert repo.audit_events[0]["action"] == "service.create"


@pytest.mark.asyncio
async def test_patch_service_merges_fields_and_get_service_raises_not_found() -> None:
    repo = InMemoryServiceRepository()
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))
    await repo.upsert_service(make_service("one", name="Original"))
    updated = await service.patch_service(
        "one", data={"name": "Patched"}, principal=ADMIN, request_id="r1"
    )
    assert updated.name == "Patched"
    assert updated.group_name == "IA"  # untouched fields survive the merge
    with pytest.raises(NotFoundError):
        await service.get_service("missing")


@pytest.mark.asyncio
async def test_patch_service_without_expected_version_is_last_write_wins() -> None:
    """Backward-compatible default: omitting expected_version keeps the prior lenient behavior."""
    repo = InMemoryServiceRepository()
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))
    await repo.upsert_service(make_service("one", name="Original"))
    await service.patch_service(
        "one", data={"name": "First writer"}, principal=ADMIN, request_id="r1"
    )
    updated = await service.patch_service(
        "one", data={"name": "Second writer"}, principal=ADMIN, request_id="r2"
    )
    assert updated.name == "Second writer"


@pytest.mark.asyncio
async def test_patch_service_with_expected_version_rejects_a_stale_concurrent_write() -> None:
    """CR-034: a client-supplied expected_version lets a concurrent stale PATCH be rejected."""
    repo = InMemoryServiceRepository()
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))
    await repo.upsert_service(make_service("one", name="Original"))

    original = await service.get_service("one")
    assert original.version == 1

    await service.patch_service(
        "one",
        data={"name": "Updated by first admin"},
        principal=ADMIN,
        request_id="r1",
        expected_version=original.version,
    )

    with pytest.raises(ConflictError):
        await service.patch_service(
            "one",
            data={"name": "Updated by second admin (stale)"},
            principal=ADMIN,
            request_id="r2",
            expected_version=original.version,
        )


@pytest.mark.asyncio
async def test_delete_service_requires_existing_row_and_audits() -> None:
    repo = InMemoryServiceRepository()
    service = ServiceApplicationService(repo, StatusService(FakeStatusCache(), None, None, 30))
    with pytest.raises(ConflictError):
        await service.delete_service("missing", principal=ADMIN, request_id="r1")
    await repo.upsert_service(make_service("one"))
    await service.delete_service("one", principal=ADMIN, request_id="r1")
    assert await repo.get_service("one") is None
    assert repo.audit_events[-1]["action"] == "service.delete"


@pytest.mark.asyncio
async def test_action_service_create_patch_preserve_id_and_delete_audits() -> None:
    """CR-005: re-submitting the same (service_id, key) via patch must reuse the existing id."""
    repo = InMemoryServiceRepository()
    action_service = ActionApplicationService(repo)
    await repo.upsert_service(make_service("one"))

    with pytest.raises(NotFoundError):
        await action_service.create_action(
            "missing-service",
            data={
                "key": "restart",
                "label": "Restart",
                "action_type": ActionType.PORTAINER,
                "risk_level": RiskLevel.OPERATE,
                "config": {"operation": "restart", "target": "selected_containers"},
            },
            principal=ADMIN,
            request_id="r1",
        )

    created = await action_service.create_action(
        "one",
        data={
            "key": "restart",
            "label": "Restart",
            "action_type": ActionType.PORTAINER,
            "risk_level": RiskLevel.OPERATE,
            "config": {"operation": "restart", "target": "selected_containers"},
        },
        principal=ADMIN,
        request_id="r1",
    )
    original_id = created.id

    with pytest.raises(ConflictError):
        await action_service.patch_action(
            "one",
            "restart",
            data={
                "key": "renamed",
                "label": "Restart",
                "action_type": ActionType.PORTAINER,
                "risk_level": RiskLevel.OPERATE,
                "config": {"operation": "restart", "target": "selected_containers"},
            },
            principal=ADMIN,
            request_id="r2",
        )

    patched = await action_service.patch_action(
        "one",
        "restart",
        data={
            "key": "restart",
            "label": "Restart (renamed label)",
            "action_type": ActionType.PORTAINER,
            "risk_level": RiskLevel.OPERATE,
            "config": {"operation": "restart", "target": "selected_containers"},
        },
        principal=ADMIN,
        request_id="r3",
    )
    assert patched.id == original_id
    assert patched.label == "Restart (renamed label)"

    await action_service.delete_action("one", "restart", principal=ADMIN, request_id="r4")
    assert await repo.get_action("one", "restart") is None
    assert [event["action"] for event in repo.audit_events] == [
        "action.create",
        "action.update",
        "action.delete",
    ]


@pytest.mark.asyncio
async def test_action_service_rejects_config_mismatched_with_declared_action_type() -> None:
    """CR-088: a config shaped for a different action_type must 422 at save time, not persist

    silently and only fail the first time someone tries to execute it.
    """
    repo = InMemoryServiceRepository()
    action_service = ActionApplicationService(repo)
    await repo.upsert_service(make_service("one"))

    with pytest.raises(ValidationError):
        await action_service.create_action(
            "one",
            data={
                "key": "backup",
                "label": "Backup",
                "action_type": ActionType.ANSIBLE,
                "risk_level": RiskLevel.OPERATE,
                # Portainer-shaped config left over from the form default, mismatched with ansible.
                "config": {"operation": "logs", "target": "selected_containers"},
            },
            principal=ADMIN,
            request_id="r1",
        )
    assert await repo.get_action("one", "backup") is None

    await repo.upsert_action(make_action("one"))
    with pytest.raises(ValidationError):
        await action_service.patch_action(
            "one",
            "restart",
            data={
                "key": "restart",
                "label": "Restart",
                "action_type": ActionType.HTTP,
                "risk_level": RiskLevel.OPERATE,
                "config": {"operation": "restart", "target": "selected_containers"},
            },
            principal=ADMIN,
            request_id="r2",
        )


@pytest.mark.asyncio
async def test_execution_service_requests_authorizes_resolves_and_enqueues() -> None:
    repo = InMemoryServiceRepository()
    queue = FakeQueue()
    execution_service = ExecutionService(repo, queue)
    await repo.upsert_service(make_service("one"))
    await repo.upsert_action(make_action("one"))

    execution, worker_task_id = await execution_service.request_execution(
        service_id="one",
        action_key="restart",
        principal=OPERATOR,
        source=ExecutionSource.UI,
        params={},
        confirmation=False,
        reason=None,
        request_id="r1",
    )
    assert worker_task_id == "task-1"
    assert queue.enqueued == [execution.id]
    assert repo.audit_events[-1]["action"] == "execution.request"
    assert await repo.get_execution(execution.id) is not None


@pytest.mark.asyncio
async def test_execution_service_rejects_unauthorized_and_invalid_config() -> None:
    repo = InMemoryServiceRepository()
    execution_service = ExecutionService(repo, FakeQueue())
    await repo.upsert_service(make_service("one"))
    await repo.upsert_action(make_action("one", key="critical-op", risk_level=RiskLevel.CRITICAL))
    with pytest.raises(AuthorizationError):
        await execution_service.request_execution(
            service_id="one",
            action_key="critical-op",
            principal=OPERATOR,
            source=ExecutionSource.UI,
            params={},
            confirmation=False,
            reason=None,
            request_id="r1",
        )

    await repo.upsert_action(make_action("one", key="bad-config", config={"operation": "restart"}))
    with pytest.raises(ValidationError):
        await execution_service.request_execution(
            service_id="one",
            action_key="bad-config",
            principal=OPERATOR,
            source=ExecutionSource.UI,
            params={},
            confirmation=False,
            reason=None,
            request_id="r1",
        )

    with pytest.raises(NotFoundError):
        await execution_service.request_execution(
            service_id="one",
            action_key="does-not-exist",
            principal=OPERATOR,
            source=ExecutionSource.UI,
            params={},
            confirmation=False,
            reason=None,
            request_id="r1",
        )


@pytest.mark.asyncio
async def test_execution_service_cancel_never_mutates_and_always_raises() -> None:
    """CR-019: cancel must not mutate execution state before rejecting (the old dead-code bug)."""
    repo = InMemoryServiceRepository()
    execution_service = ExecutionService(repo, FakeQueue())
    execution = Execution(
        service_id="one",
        service_id_snapshot="one",
        action_definition_id=uuid4(),
        action_key="restart",
        requested_by_subject="u",
        source=ExecutionSource.UI,
        correlation_id="r",
    )
    await repo.create_execution(execution)

    with pytest.raises(NotFoundError):
        await execution_service.cancel(uuid4())
    with pytest.raises(ConflictError):
        await execution_service.cancel(execution.id)
    unchanged = await repo.get_execution(execution.id)
    assert unchanged is not None and unchanged.status == execution.status


@pytest.mark.asyncio
async def test_catalog_reimport_preserves_action_id() -> None:
    """CR-005: the real business key is (service_id, key), not id — reimport must be idempotent."""
    repo = InMemoryServiceRepository()
    raw = """version: 1
services:
  - id: one
    name: One
    group_name: G
    environment: dev
    actions:
      - key: restart
        label: Restart
        action_type: portainer
        risk_level: operate
        config: {operation: restart, target: selected_containers}
"""
    catalog = parse_catalog_yaml(raw)
    await upsert_catalog(repo, catalog)
    first_id = (await repo.get_action("one", "restart")).id  # type: ignore[union-attr]
    await upsert_catalog(repo, catalog)
    second_id = (await repo.get_action("one", "restart")).id  # type: ignore[union-attr]
    assert first_id == second_id


@pytest.mark.asyncio
async def test_export_catalog_round_trips_service_and_action_shape() -> None:
    repo = InMemoryServiceRepository()
    await repo.upsert_service(
        make_service(
            "one",
            portainer_environment_id="5",
            portainer_stack_name="stack",
            container_selectors={"containers": [{"name": "one"}], "aggregation": "all_required"},
        )
    )
    await repo.upsert_action(make_action("one"))
    exported = await export_catalog(repo)
    reparsed = parse_catalog_yaml(exported)
    assert reparsed.services[0].id == "one"
    assert reparsed.services[0].portainer is not None
    assert reparsed.services[0].portainer.environment_id == "5"
    assert reparsed.services[0].actions[0].key == "restart"
