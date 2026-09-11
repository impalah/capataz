"""Unit tests for the application-layer use cases: services, actions, executions and the
request-scoped connector resolver, over the shared in-memory repository double (fakes.py)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fakes import (
    TEST_SUFFIXES,
    FakeConnectorFactory,
    FakeMetrics,
    FakePlatform,
    FakeQueue,
    InMemoryServiceRepository,
    make_action,
    make_cipher,
    make_service,
    runtime,
    seed_connectors,
)

from capataz_api.application.services import (
    ActionApplicationService,
    ConnectorResolver,
    ExecutionService,
    ServiceApplicationService,
    StatusService,
)
from capataz_api.domain.entities import Connector, Execution, Principal
from capataz_api.domain.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from capataz_api.domain.value_objects import ActionType, ExecutionSource, RiskLevel

ADMIN = Principal("admin", {"capataz-admin"})
OPERATOR = Principal("operator", {"capataz-operator"})
RESTART: dict[str, Any] = {
    "key": "restart",
    "label": "Restart",
    "risk_level": RiskLevel.OPERATE,
    "connector": "portainer_main",
    "config": {"operation": "restart", "target": "selected_containers"},
}


def service_app(
    repo: InMemoryServiceRepository, factory: FakeConnectorFactory | None = None
) -> ServiceApplicationService:
    return ServiceApplicationService(
        repo, StatusService(factory or FakeConnectorFactory()), make_cipher(), TEST_SUFFIXES
    )


def seeded_repo() -> InMemoryServiceRepository:
    repo = InMemoryServiceRepository()
    seed_connectors(repo)
    return repo


# --- listing / status -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_services_status_filter_attributes_status_by_id_not_dict_equality() -> None:
    """Regression test for CR-016/CR-063: status filtering is a repository-level lookup keyed by
    id (status_cache), so two services with identical display fields never swap statuses."""
    repo = InMemoryServiceRepository()
    await repo.upsert_service(make_service("twin-a"))
    await repo.upsert_service(make_service("twin-b"))
    await repo.update_status_cache("twin-a", "healthy")
    await repo.update_status_cache("twin-b", "down")

    items, total = await service_app(repo).list_services(
        group_name=None, environment=None, status="healthy", offset=0, limit=20
    )
    assert [item.id for item in items] == ["twin-a"]
    assert total == 1


@pytest.mark.asyncio
async def test_list_services_status_filter_paginates_correctly_across_pages() -> None:
    repo = InMemoryServiceRepository()
    for index in range(5):
        await repo.upsert_service(make_service(f"svc-{index}"))
        await repo.update_status_cache(f"svc-{index}", "healthy" if index < 3 else "down")
    service = service_app(repo)

    page1, total1 = await service.list_services(
        group_name=None, environment=None, status="healthy", offset=0, limit=2
    )
    page2, total2 = await service.list_services(
        group_name=None, environment=None, status="healthy", offset=2, limit=2
    )
    assert (total1, total2) == (3, 3)
    assert len(page1) == 2
    assert [item.id for item in page2] == ["svc-2"]


@pytest.mark.asyncio
async def test_refresh_status_writes_the_computed_status_to_the_status_cache_column() -> None:
    repo = InMemoryServiceRepository()
    await repo.upsert_service(make_service("svc", maintenance=True))
    await service_app(repo).refresh_status("svc")
    assert repo.status_cache["svc"] == "maintenance"


@pytest.mark.asyncio
async def test_refresh_status_includes_metrics_from_the_referenced_connector() -> None:
    repo = seeded_repo()
    await repo.upsert_service(
        make_service(
            "svc",
            observability={"metrics": [{"label": "CPU", "connector": "prometheus", "query": "up"}]},
        )
    )
    factory = FakeConnectorFactory(metrics=FakeMetrics(value=42.0))
    result = await service_app(repo, factory).refresh_status("svc")
    assert result["metrics"] == [{"label": "CPU", "value": 42.0}]


# --- create / patch / delete ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_service_rejects_duplicate_id_and_audits() -> None:
    repo = InMemoryServiceRepository()
    service = service_app(repo)
    data = {"id": "one", "name": "One", "group_name": "G", "environment": "dev"}
    await service.create_service(data=data, principal=ADMIN, request_id="r1")
    with pytest.raises(ConflictError):
        await service.create_service(data=data, principal=ADMIN, request_id="r2")
    assert repo.audit_events[0]["action"] == "service.create"


@pytest.mark.asyncio
async def test_create_service_validates_connector_references_and_capabilities() -> None:
    repo = seeded_repo()
    service = service_app(repo)
    base = {"id": "one", "name": "One", "group_name": "G", "environment": "dev"}

    with pytest.raises(ValidationError) as missing:
        await service.create_service(
            data={**base, "runtime": runtime(connector="ghost")}, principal=ADMIN, request_id="r"
        )
    assert missing.value.field_errors[0].path == "runtime.connector"

    with pytest.raises(ValidationError, match="cannot be used for status"):
        await service.create_service(
            data={**base, "runtime": runtime(connector="grafana")}, principal=ADMIN, request_id="r"
        )
    assert "one" not in repo.services


@pytest.mark.asyncio
async def test_create_service_rejects_a_health_url_outside_the_allow_list() -> None:
    service = service_app(seeded_repo())
    with pytest.raises(ValidationError) as excinfo:
        await service.create_service(
            data={
                "id": "one",
                "name": "One",
                "group_name": "G",
                "environment": "dev",
                "observability": {
                    "health": {"connector": "http", "url": "https://evil.example.com/health"}
                },
            },
            principal=ADMIN,
            request_id="r",
        )
    assert excinfo.value.field_errors[0].path == "observability.health.url"


@pytest.mark.asyncio
async def test_create_service_rejects_an_invalid_spec() -> None:
    with pytest.raises(ValidationError, match="Invalid service"):
        await service_app(InMemoryServiceRepository()).create_service(
            data={
                "id": "one",
                "name": "One",
                "group_name": "G",
                "environment": "dev",
                "tags": ["No!"],
            },
            principal=ADMIN,
            request_id="r",
        )


@pytest.mark.asyncio
async def test_patch_service_replaces_only_the_supplied_top_level_fields() -> None:
    repo = seeded_repo()
    service = service_app(repo)
    await repo.upsert_service(
        make_service(
            "one",
            name="Original",
            runtime=runtime(names=("one",)),
            observability={"logs": {"connector": "loki", "query": "{a}"}},
        )
    )
    updated = await service.patch_service(
        "one", data={"name": "Patched"}, principal=ADMIN, request_id="r1"
    )
    assert updated.name == "Patched"
    assert updated.group_name == "IA"
    assert updated.spec.runtime is not None  # untouched fields survive the merge

    replaced = await service.patch_service(
        "one", data={"observability": {"metrics": []}}, principal=ADMIN, request_id="r2"
    )
    assert replaced.spec.observability.logs is None  # the whole field was replaced
    with pytest.raises(NotFoundError):
        await service.get_service("missing")


@pytest.mark.asyncio
async def test_patch_service_without_expected_version_is_last_write_wins() -> None:
    repo = InMemoryServiceRepository()
    service = service_app(repo)
    await repo.upsert_service(make_service("one", name="Original"))
    await service.patch_service("one", data={"name": "First"}, principal=ADMIN, request_id="r1")
    updated = await service.patch_service(
        "one", data={"name": "Second"}, principal=ADMIN, request_id="r2"
    )
    assert updated.name == "Second"


@pytest.mark.asyncio
async def test_patch_service_with_expected_version_rejects_a_stale_concurrent_write() -> None:
    """CR-034: a client-supplied expected_version lets a concurrent stale PATCH be rejected."""
    repo = InMemoryServiceRepository()
    service = service_app(repo)
    await repo.upsert_service(make_service("one", name="Original"))
    original = await service.get_service("one")
    await service.patch_service(
        "one",
        data={"name": "First admin"},
        principal=ADMIN,
        request_id="r1",
        expected_version=original.version,
    )
    with pytest.raises(ConflictError):
        await service.patch_service(
            "one",
            data={"name": "Second admin (stale)"},
            principal=ADMIN,
            request_id="r2",
            expected_version=original.version,
        )


@pytest.mark.asyncio
async def test_delete_service_requires_existing_row_and_audits() -> None:
    repo = InMemoryServiceRepository()
    service = service_app(repo)
    with pytest.raises(ConflictError):
        await service.delete_service("missing", principal=ADMIN, request_id="r1")
    await repo.upsert_service(make_service("one"))
    await service.delete_service("one", principal=ADMIN, request_id="r1")
    assert await repo.get_service("one") is None
    assert repo.audit_events[-1]["action"] == "service.delete"


# --- links ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_links_resolves_a_deep_link_to_the_swarm_service() -> None:
    repo = seeded_repo()
    await repo.upsert_service(
        make_service(
            "authentik",
            runtime=runtime(kind="services", names=("authentik-server",), stack_name="authentik"),
        )
    )
    platform = FakePlatform(link_target="abc123")
    links = await service_app(repo, FakeConnectorFactory(platform=platform)).get_links("authentik")
    assert links["portainer"] == "https://portainer.home.arpa/#!/7/docker/services/abc123"
    assert platform.calls[0][1]["stack_name"] == "authentik"


@pytest.mark.asyncio
async def test_get_links_falls_back_to_the_list_page_when_portainer_is_unreachable() -> None:
    repo = seeded_repo()
    await repo.upsert_service(make_service("one", runtime=runtime(names=("one",))))
    factory = FakeConnectorFactory(
        platform=FakePlatform(error=ExternalServiceError("Portainer is unavailable"))
    )
    links = await service_app(repo, factory).get_links("one")
    assert links["portainer"] == "https://portainer.home.arpa/#!/7/docker/containers"


@pytest.mark.asyncio
async def test_get_links_without_a_runtime_never_calls_the_platform() -> None:
    repo = seeded_repo()
    await repo.upsert_service(make_service("one", service_url="https://one.home.arpa"))
    platform = FakePlatform()
    links = await service_app(repo, FakeConnectorFactory(platform=platform)).get_links("one")
    assert links == {"service": "https://one.home.arpa/"}
    assert platform.calls == []


# --- actions --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_service_create_patch_preserve_id_and_delete_audits() -> None:
    """CR-005: re-submitting the same (service_id, key) via patch must reuse the existing id."""
    repo = seeded_repo()
    actions = ActionApplicationService(repo)
    await repo.upsert_service(make_service("one", runtime=runtime(names=("one",))))

    with pytest.raises(NotFoundError):
        await actions.create_action("missing", data=RESTART, principal=ADMIN, request_id="r1")

    created = await actions.create_action("one", data=RESTART, principal=ADMIN, request_id="r1")
    assert created.action_type is ActionType.PORTAINER
    assert created.connector_id == "portainer_main"

    with pytest.raises(ConflictError):
        await actions.patch_action(
            "one", "restart", data={**RESTART, "key": "renamed"}, principal=ADMIN, request_id="r2"
        )
    patched = await actions.patch_action(
        "one",
        "restart",
        data={**RESTART, "label": "Restart (renamed)"},
        principal=ADMIN,
        request_id="r3",
    )
    assert patched.id == created.id
    assert patched.label == "Restart (renamed)"

    await actions.delete_action("one", "restart", principal=ADMIN, request_id="r4")
    assert await repo.get_action("one", "restart") is None
    assert [event["action"] for event in repo.audit_events] == [
        "action.create",
        "action.update",
        "action.delete",
    ]


@pytest.mark.asyncio
async def test_action_service_requires_an_existing_connector() -> None:
    repo = seeded_repo()
    await repo.upsert_service(make_service("one", runtime=runtime(names=("one",))))
    with pytest.raises(ValidationError, match="does not exist"):
        await ActionApplicationService(repo).create_action(
            "one", data={**RESTART, "connector": "ghost"}, principal=ADMIN, request_id="r1"
        )


@pytest.mark.asyncio
async def test_action_service_rejects_config_mismatched_with_its_connector_type() -> None:
    """CR-088: a config shaped for another connector type must 422 at save time."""
    repo = seeded_repo()
    await repo.upsert_service(make_service("one", runtime=runtime(names=("one",))))
    with pytest.raises(ValidationError):
        await ActionApplicationService(repo).create_action(
            "one",
            data={**RESTART, "key": "backup", "connector": "ansible_homelab"},
            principal=ADMIN,
            request_id="r1",
        )
    assert await repo.get_action("one", "backup") is None


@pytest.mark.asyncio
async def test_action_type_is_derived_from_the_connector_and_config_normalized() -> None:
    repo = seeded_repo()
    await repo.upsert_service(make_service("one"))
    created = await ActionApplicationService(repo).create_action(
        "one",
        data={
            "key": "disk",
            "label": "Disk usage",
            "risk_level": RiskLevel.READ,
            "connector": "ssh_mole",
            "config": {"command_id": "disk_usage"},
        },
        principal=ADMIN,
        request_id="r1",
    )
    assert created.action_type is ActionType.SSH
    assert created.config == {"command_id": "disk_usage", "params": {}}


# --- executions -----------------------------------------------------------------------------


async def _execution_setup() -> tuple[InMemoryServiceRepository, FakeQueue, ExecutionService]:
    repo = seeded_repo()
    queue = FakeQueue()
    await repo.upsert_service(make_service("one", runtime=runtime(names=("one",))))
    return repo, queue, ExecutionService(repo, queue)


def _request(**overrides: Any) -> dict[str, Any]:
    return {
        "service_id": "one",
        "action_key": "restart",
        "principal": OPERATOR,
        "source": ExecutionSource.UI,
        "params": {},
        "confirmation": False,
        "reason": None,
        "request_id": "r1",
        **overrides,
    }


@pytest.mark.asyncio
async def test_execution_service_requests_authorizes_resolves_and_enqueues() -> None:
    repo, queue, executions = await _execution_setup()
    await repo.upsert_action(make_action("one"))
    execution, worker_task_id = await executions.request_execution(**_request())
    assert worker_task_id == "task-1"
    assert queue.enqueued == [execution.id]
    assert repo.audit_events[-1]["action"] == "execution.request"
    assert await repo.get_execution(execution.id) is not None


@pytest.mark.asyncio
async def test_execution_service_rejects_unauthorized_invalid_and_orphaned_actions() -> None:
    repo, _queue, executions = await _execution_setup()
    await repo.upsert_action(make_action("one", key="critical-op", risk_level=RiskLevel.CRITICAL))
    with pytest.raises(AuthorizationError):
        await executions.request_execution(**_request(action_key="critical-op"))

    await repo.upsert_action(make_action("one", key="bad-config", config={"operation": "restart"}))
    with pytest.raises(ValidationError):
        await executions.request_execution(**_request(action_key="bad-config"))

    await repo.upsert_action(make_action("one", key="orphan", connector_id="gone"))
    with pytest.raises(ValidationError, match="no longer exists"):
        await executions.request_execution(**_request(action_key="orphan"))

    with pytest.raises(NotFoundError):
        await executions.request_execution(**_request(action_key="does-not-exist"))


@pytest.mark.asyncio
async def test_execution_service_cancel_never_mutates_and_always_raises() -> None:
    """CR-019: cancel must not mutate execution state before rejecting (the old dead-code bug)."""
    repo = InMemoryServiceRepository()
    executions = ExecutionService(repo, FakeQueue())
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
        await executions.cancel(uuid4())
    with pytest.raises(ConflictError):
        await executions.cancel(execution.id)
    unchanged = await repo.get_execution(execution.id)
    assert unchanged is not None and unchanged.status == execution.status


# --- connector resolver ---------------------------------------------------------------------


class _CountingRepo(InMemoryServiceRepository):
    def __init__(self) -> None:
        super().__init__()
        self.connector_reads = 0

    async def get_connector(self, connector_id: str) -> Connector | None:
        self.connector_reads += 1
        return await super().get_connector(connector_id)


@pytest.mark.asyncio
async def test_connector_resolver_caches_lookups_and_decrypts_stripped_secrets() -> None:
    repo = _CountingRepo()
    seed_connectors(repo)
    resolver = ConnectorResolver(repo, make_cipher())
    first = await resolver.get("portainer_main")
    await resolver.get("portainer_main")
    assert repo.connector_reads == 1
    assert await resolver.secrets_for(first) == {"token": "pt-secret"}
    with pytest.raises(ConfigurationError, match="does not exist"):
        await resolver.get("ghost")
