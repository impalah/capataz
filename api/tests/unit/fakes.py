"""Shared in-memory test doubles and builders for the unit suites.

One ServiceRepository double (router-level and application-level tests used to keep two drifting
copies), builders for services/connectors/resources/actions, and a connector client factory
whose platform/prober/metrics fakes each test can configure.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import UUID

from capataz_api.domain.entities import ActionDefinition, Connector, Execution, Resource, Service
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.specs import CONNECTOR_SPEC_ADAPTER, ServiceSpec
from capataz_api.domain.value_objects import ActionType, ResourceType, RiskLevel
from capataz_api.infrastructure.crypto import FernetResourceCipher

# Test-only Fernet key (same one as the shared API/runner crypto vector).
TEST_MASTER_KEY = "8tqAJmPr27f8r7U4yZZMgMC8TR44rrc-Zdrdru4ONDo="
TEST_SUFFIXES = (".home.arpa",)


def make_cipher() -> FernetResourceCipher:
    return FernetResourceCipher([TEST_MASTER_KEY])


class InMemoryServiceRepository:
    def __init__(self) -> None:
        self.services: dict[str, Service] = {}
        self.actions: dict[tuple[str, str], ActionDefinition] = {}
        self.executions: dict[UUID, Execution] = {}
        self.audit_events: list[dict[str, Any]] = []
        self.status_cache: dict[str, str] = {}
        self.resources: dict[str, Resource] = {}
        self.connectors: dict[str, Connector] = {}

    # --- services ---------------------------------------------------------------------------

    async def get_service(self, service_id: str) -> Service | None:
        # A real repository always builds a fresh domain object from storage; copy here too, so
        # two independent get_service calls can never alias the same instance.
        service = self.services.get(service_id)
        return deepcopy(service) if service is not None else None

    async def list_services(self, **filters: object) -> tuple[list[Service], int]:
        items = [deepcopy(service) for service in self.services.values()]
        if group := filters.get("group_name"):
            items = [service for service in items if service.group_name == group]
        if environment := filters.get("environment"):
            items = [service for service in items if service.environment == environment]
        if status := filters.get("status"):
            items = [service for service in items if self.status_cache.get(service.id) == status]
        offset = int(str(filters.get("offset") or 0))
        limit = filters.get("limit")
        page = items[offset : offset + int(str(limit))] if limit is not None else items[offset:]
        return page, len(items)

    async def update_status_cache(self, service_id: str, status: str) -> None:
        self.status_cache[service_id] = status

    async def upsert_service(self, service: Service, *, enforce_version: bool = False) -> Service:
        existing = self.services.get(service.id)
        if existing is not None and enforce_version and existing.version != service.version:
            raise ConflictError("The record was modified by another request; reload and retry")
        stored = deepcopy(service)
        stored.version = existing.version + 1 if existing is not None else 1
        self.services[service.id] = stored
        return deepcopy(stored)

    async def delete_service(self, service_id: str) -> bool:
        return self.services.pop(service_id, None) is not None

    # --- actions ----------------------------------------------------------------------------

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

    async def list_actions_by_connector(self, connector_id: str) -> list[ActionDefinition]:
        return [action for action in self.actions.values() if action.connector_id == connector_id]

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

    # --- executions / audit -----------------------------------------------------------------

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
        # Mirror SqlAlchemyRepository.append_audit's default: metadata is stored as {} when the
        # caller (build_audit_event) omitted it, never left missing.
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

    # --- resources / connectors -------------------------------------------------------------

    async def get_resource(self, resource_id: str) -> Resource | None:
        resource = self.resources.get(resource_id)
        return deepcopy(resource) if resource is not None else None

    async def list_resources(self) -> list[Resource]:
        return [deepcopy(self.resources[key]) for key in sorted(self.resources)]

    async def upsert_resource(self, resource: Resource) -> Resource:
        existing = self.resources.get(resource.id)
        stored = deepcopy(resource)
        stored.version = existing.version + 1 if existing is not None else 1
        self.resources[resource.id] = stored
        return deepcopy(stored)

    async def delete_resource(self, resource_id: str) -> bool:
        return self.resources.pop(resource_id, None) is not None

    async def get_connector(self, connector_id: str) -> Connector | None:
        connector = self.connectors.get(connector_id)
        return deepcopy(connector) if connector is not None else None

    async def list_connectors(self) -> list[Connector]:
        return [deepcopy(self.connectors[key]) for key in sorted(self.connectors)]

    async def upsert_connector(
        self, connector: Connector, *, enforce_version: bool = False
    ) -> Connector:
        existing = self.connectors.get(connector.id)
        if existing is not None and enforce_version and existing.version != connector.version:
            raise ConflictError("The record was modified by another request; reload and retry")
        stored = deepcopy(connector)
        stored.version = existing.version + 1 if existing is not None else 1
        self.connectors[connector.id] = stored
        return deepcopy(stored)

    async def delete_connector(self, connector_id: str) -> bool:
        return self.connectors.pop(connector_id, None) is not None


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    async def enqueue(self, execution_id: UUID) -> str:
        self.enqueued.append(execution_id)
        return "task-1"


# --- builders ---------------------------------------------------------------------------------


def make_spec(**overrides: Any) -> ServiceSpec:
    data: dict[str, Any] = {"name": "Open WebUI", "group_name": "IA", "environment": "homelab"}
    data.update(overrides)
    return ServiceSpec.model_validate(data)


def make_service(service_id: str = "open-webui", **overrides: Any) -> Service:
    version = int(overrides.pop("version", 1))
    return Service(id=service_id, spec=make_spec(**overrides), version=version)


def runtime(
    *,
    connector: str = "portainer_main",
    kind: str = "containers",
    names: tuple[str, ...] = ("open-webui",),
    environment_id: str = "7",
    stack_name: str | None = None,
) -> dict[str, Any]:
    return {
        "connector": connector,
        "environment_id": environment_id,
        "stack_name": stack_name,
        kind: [{"name": name} for name in names],
    }


def make_connector(connector_id: str, connector_type: str, **config: Any) -> Connector:
    return Connector(
        spec=CONNECTOR_SPEC_ADAPTER.validate_python(
            {"id": connector_id, "type": connector_type, "config": config}
        )
    )


def portainer_connector(connector_id: str = "portainer_main") -> Connector:
    return make_connector(
        connector_id, "portainer", url="https://portainer.home.arpa", token="portainer_token"
    )


def http_connector(connector_id: str = "http") -> Connector:
    return make_connector(connector_id, "http")


def prometheus_connector(connector_id: str = "prometheus") -> Connector:
    return make_connector(connector_id, "prometheus", url="https://prometheus.home.arpa")


def grafana_connector(
    connector_id: str = "grafana", url: str = "https://grafana.home.arpa"
) -> Connector:
    return make_connector(connector_id, "grafana", url=url)


def loki_connector(connector_id: str = "loki") -> Connector:
    return make_connector(connector_id, "loki", url="https://loki.home.arpa")


def ansible_connector(connector_id: str = "ansible_homelab") -> Connector:
    return make_connector(
        connector_id,
        "ansible",
        inventory="inventories/homelab.yml",
        private_key="ssh_key",
        known_hosts="known_hosts",
    )


def ssh_connector(connector_id: str = "ssh_mole") -> Connector:
    return make_connector(
        connector_id,
        "ssh",
        host="mole.home.arpa",
        user="capataz",
        private_key="ssh_key",
        known_hosts="known_hosts",
    )


def make_resource(
    resource_id: str,
    resource_type: ResourceType = ResourceType.SECRET,
    content: bytes = b"secret-token",
    **overrides: Any,
) -> Resource:
    cipher = make_cipher()
    return Resource(
        id=resource_id,
        type=resource_type,
        ciphertext=cipher.encrypt(content),
        fingerprint=cipher.fingerprint(content),
        size=len(content),
        **overrides,
    )


def seed_connectors(repo: InMemoryServiceRepository) -> None:
    """The connectors most tests need, plus the portainer token (with a trailing newline, as a
    file-sourced secret would have) they reference."""
    for connector in (
        portainer_connector(),
        http_connector(),
        prometheus_connector(),
        grafana_connector(),
        loki_connector(),
        ansible_connector(),
        ssh_connector(),
    ):
        repo.connectors[connector.id] = connector
    repo.resources["portainer_token"] = make_resource("portainer_token", content=b"pt-secret\n")


def make_action(
    service_id: str = "open-webui",
    key: str = "restart",
    *,
    connector_id: str = "portainer_main",
    action_type: ActionType = ActionType.PORTAINER,
    risk_level: RiskLevel = RiskLevel.OPERATE,
    config: dict[str, Any] | None = None,
    **overrides: Any,
) -> ActionDefinition:
    return ActionDefinition(
        service_id=service_id,
        key=key,
        label="Restart",
        action_type=action_type,
        risk_level=risk_level,
        connector_id=connector_id,
        config=config
        if config is not None
        else {"operation": "restart", "target": "selected_containers"},
        **overrides,
    )


# --- connector client fakes ---------------------------------------------------------------------


class FakePlatform:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        link_target: str | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.error, self.link_target = error, link_target
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def container_states(
        self, environment_id: str, selectors: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.calls.append((environment_id, selectors))
        if self.error:
            raise self.error
        return self.rows

    async def find_link_target(self, environment_id: str, selectors: dict[str, Any]) -> str | None:
        self.calls.append((environment_id, selectors))
        if self.error:
            raise self.error
        return self.link_target


class FakeProber:
    def __init__(self, healthy: bool = True, error: Exception | None = None) -> None:
        self.healthy, self.error = healthy, error
        self.configs: list[dict[str, Any]] = []

    async def probe(self, config: dict[str, Any]) -> bool:
        self.configs.append(config)
        if self.error:
            raise self.error
        return self.healthy


class FakeMetrics:
    def __init__(self, value: float = 1.0, error: Exception | None = None) -> None:
        self.value, self.error = value, error
        self.queries: list[list[dict[str, Any]]] = []

    async def query(self, definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.queries.append(definitions)
        if self.error:
            raise self.error
        return [{"label": item["label"], "value": self.value} for item in definitions]


class FakeConnectorFactory:
    def __init__(
        self,
        platform: FakePlatform | None = None,
        prober: FakeProber | None = None,
        metrics: FakeMetrics | Mapping[str, FakeMetrics] | None = None,
    ) -> None:
        self.platform_fake = platform or FakePlatform()
        self.prober_fake = prober or FakeProber()
        self.metrics_fakes = metrics if metrics is not None else FakeMetrics()
        self.secrets_seen: list[dict[str, str]] = []

    def platform(self, connector: Connector, secrets: Mapping[str, str]) -> FakePlatform:
        self.secrets_seen.append(dict(secrets))
        return self.platform_fake

    def metrics(self, connector: Connector, secrets: Mapping[str, str]) -> FakeMetrics:
        if isinstance(self.metrics_fakes, FakeMetrics):
            return self.metrics_fakes
        return self.metrics_fakes[connector.id]

    def prober(self, connector: Connector) -> FakeProber:
        return self.prober_fake
