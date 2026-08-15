from pathlib import Path
from uuid import uuid4

import pytest

from capataz_api.adapters.outbound.health import validate_health_url
from capataz_api.application.policies import (
    ContainerObservation,
    aggregate_status,
    authorize_action,
    resolve_action,
    resolve_links,
    sanitize,
)
from capataz_api.application.policies.rbac import ROLE_ADMIN, ROLE_OPERATOR
from capataz_api.application.services.catalog import parse_catalog_yaml, upsert_catalog
from capataz_api.application.services.status import StatusService
from capataz_api.domain.entities import ActionDefinition, Execution, Principal, Service
from capataz_api.domain.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    ValidationError,
)
from capataz_api.domain.value_objects import (
    ActionType,
    ExecutionSource,
    ExecutionStatus,
    RiskLevel,
    ServiceStatus,
)
from capataz_api.infrastructure.secrets import FileSecretReader


class FakeRepo:
    def __init__(self) -> None:
        self.services: dict[str, Service] = {}
        self.actions: dict[tuple[str, str], ActionDefinition] = {}

    async def get_service(self, service_id: str) -> Service | None:
        return self.services.get(service_id)

    async def upsert_service(self, item: Service) -> Service:
        self.services[item.id] = item
        return item

    async def upsert_action(self, item: ActionDefinition) -> ActionDefinition:
        self.actions[(item.service_id, item.key)] = item
        return item


def service() -> Service:
    return Service(
        id="open-webui",
        name="Open WebUI",
        group_name="AI",
        environment="homelab",
        container_selectors={"containers": [{"name": "open-webui"}]},
    )


def test_aggregate_status_rules() -> None:
    assert aggregate_status([], None, maintenance=True) == ServiceStatus.MAINTENANCE
    assert aggregate_status(None, None, integration_available=False) == ServiceStatus.UNKNOWN
    assert aggregate_status([ContainerObservation(False)], None) == ServiceStatus.DOWN
    assert aggregate_status([ContainerObservation(True, False)], True) == ServiceStatus.DEGRADED
    assert aggregate_status([ContainerObservation(True, True)], True) == ServiceStatus.HEALTHY
    assert (
        aggregate_status(
            [ContainerObservation(True), ContainerObservation(False)],
            True,
            aggregation="any_healthy",
        )
        == ServiceStatus.HEALTHY
    )


def test_aggregate_status_any_healthy_survives_all_required_containers_being_down() -> None:
    """CR-007: any_healthy must not be short-circuited by the all-required-down DOWN check."""
    observations = [
        ContainerObservation(running=False, required=True),
        ContainerObservation(running=True, healthy=True, required=False),
    ]
    assert aggregate_status(observations, None, aggregation="any_healthy") == ServiceStatus.HEALTHY
    # Same containers, all_required mode: every required container down is still DOWN.
    assert aggregate_status(observations, None, aggregation="all_required") == ServiceStatus.DOWN


def test_catalog_validation_and_no_free_command() -> None:
    raw = """version: 1
services:
  - id: open-webui
    name: Open WebUI
    group_name: AI
    environment: homelab
    actions:
      - key: restart
        label: Restart
        action_type: portainer
        risk_level: operate
        config: {operation: restart, target: selected_containers}
"""
    assert parse_catalog_yaml(raw).services[0].id == "open-webui"
    invalid = raw.replace("operation: restart, target: selected_containers", "command: rm -rf /")
    with pytest.raises(ValidationError) as excinfo:
        parse_catalog_yaml(invalid)
    (field_error,) = excinfo.value.field_errors
    assert field_error.path == "services.0.actions.0"
    assert field_error.line == 8  # the "- key: restart" line the bad action block starts at


def test_catalog_rejects_extra_portainer_config_keys() -> None:
    raw = """version: 1
services:
  - id: open-webui
    name: Open WebUI
    group_name: AI
    environment: homelab
    actions:
      - key: restart
        label: Restart
        action_type: portainer
        risk_level: operate
        config: {operation: restart, target: selected_containers, extra: nope}
"""
    with pytest.raises(ValidationError):
        parse_catalog_yaml(raw)


@pytest.mark.asyncio
async def test_catalog_upsert_is_idempotent() -> None:
    repo = FakeRepo()
    catalog = parse_catalog_yaml("""version: 1
services:
  - id: one
    name: One
    group_name: G
    environment: dev
    actions: []
""")
    first = await upsert_catalog(repo, catalog)
    second = await upsert_catalog(repo, catalog)
    assert list(repo.services) == ["one"]
    assert (first.created, first.updated) == (1, 0)
    assert (second.created, second.updated) == (0, 1)


@pytest.mark.asyncio
async def test_status_service_refreshes_and_caches() -> None:
    class Cache:
        value: dict[str, object] | None = None

        async def get(self, key: str) -> dict[str, object] | None:
            return self.value

        async def set(self, key: str, value: dict[str, object], ttl: int) -> None:
            self.value = value

    class Platform:
        async def container_states(
            self, environment_id: str, selectors: dict[str, object]
        ) -> list[dict[str, object]]:
            return [{"name": "open-webui", "running": True, "healthy": True}]

    class Prober:
        async def probe(self, config: dict[str, object]) -> bool:
            return True

    item = service()
    item.portainer_environment_id = "1"
    item.health_config = {"url": "https://openwebui.home.arpa/health"}
    status = StatusService(Cache(), Platform(), Prober(), 30)
    assert (await status.refresh(item))["status"] == "healthy"
    assert (await status.get(item))["service_id"] == "open-webui"


@pytest.mark.asyncio
async def test_status_service_surfaces_portainer_failure_without_hiding_health_probe() -> None:
    class Cache:
        value: dict[str, object] | None = None

        async def get(self, key: str) -> dict[str, object] | None:
            return self.value

        async def set(self, key: str, value: dict[str, object], ttl: int) -> None:
            self.value = value

    class FailingPlatform:
        async def container_states(
            self, environment_id: str, selectors: dict[str, object]
        ) -> list[dict[str, object]]:
            raise ExternalServiceError("Portainer authentication was rejected")

    class Prober:
        async def probe(self, config: dict[str, object]) -> bool:
            return True

    item = service()
    item.portainer_environment_id = "1"
    item.health_config = {"url": "https://openwebui.home.arpa/health"}
    status = StatusService(Cache(), FailingPlatform(), Prober(), 30)
    result = await status.refresh(item)
    assert result["error"] == "Portainer authentication was rejected"
    assert result["external_healthy"] is True
    assert result["containers"] == []


@pytest.mark.asyncio
async def test_status_service_reports_unexpected_errors_without_leaking_internals() -> None:
    class Cache:
        value: dict[str, object] | None = None

        async def get(self, key: str) -> dict[str, object] | None:
            return self.value

        async def set(self, key: str, value: dict[str, object], ttl: int) -> None:
            self.value = value

    class BuggyPlatform:
        async def container_states(
            self, environment_id: str, selectors: dict[str, object]
        ) -> list[dict[str, object]]:
            raise RuntimeError("boom: /internal/path leaked")

    item = service()
    item.portainer_environment_id = "1"
    status = StatusService(Cache(), BuggyPlatform(), None, 30)
    result = await status.refresh(item)
    assert result["error"] == "Unexpected error checking Portainer status"
    assert "boom" not in result["error"]


def test_rbac_risk_and_allowlisted_action_resolution() -> None:
    operator = Principal("op", {ROLE_OPERATOR})
    admin = Principal("admin", {ROLE_ADMIN})
    authorize_action(operator, RiskLevel.OPERATE, False, None)
    with pytest.raises(AuthorizationError):
        authorize_action(operator, RiskLevel.CRITICAL, True, "reason")
    with pytest.raises(AuthorizationError):
        authorize_action(admin, RiskLevel.CRITICAL, True, None)
    action = ActionDefinition(
        service_id="open-webui",
        key="restart",
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        config={"operation": "restart", "target": "selected_containers"},
        allowed_parameters_schema={"properties": {"mode": {"enum": ["safe"]}}},
    )
    assert resolve_action(service(), action, {"mode": "safe"})["config"]["operation"] == "restart"
    with pytest.raises(ValidationError):
        resolve_action(service(), action, {"container_id": "untrusted"})


def test_resolve_action_rejects_extra_portainer_keys_and_distinguishes_errors() -> None:
    action = ActionDefinition(
        service_id="open-webui",
        key="restart",
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        config={"operation": "restart", "target": "selected_containers", "extra": "nope"},
    )
    with pytest.raises(ValidationError, match="must contain only operation and target"):
        resolve_action(service(), action, {})

    disabled = ActionDefinition(
        service_id="open-webui",
        key="restart",
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        enabled=False,
        config={"operation": "restart", "target": "selected_containers"},
    )
    with pytest.raises(ValidationError, match="not enabled"):
        resolve_action(service(), disabled, {})

    wrong_service = ActionDefinition(
        service_id="other-service",
        key="restart",
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        config={"operation": "restart", "target": "selected_containers"},
    )
    with pytest.raises(ValidationError, match="does not belong to this service"):
        resolve_action(service(), wrong_service, {})


def test_execution_transition_and_sanitization() -> None:
    execution = Execution(
        service_id="one",
        service_id_snapshot="one",
        action_definition_id=uuid4(),
        action_key="restart",
        requested_by_subject="u",
        source=ExecutionSource.UI,
        correlation_id="r",
    )
    execution.transition_to(ExecutionStatus.RUNNING)
    execution.transition_to(ExecutionStatus.SUCCEEDED)
    assert execution.finished_at is not None
    with pytest.raises(ConflictError):
        execution.transition_to(ExecutionStatus.RUNNING)
    assert sanitize({"token": "secret", "line": "Bearer abc.def.ghi"}) == {
        "token": "[REDACTED]",
        "line": "Bearer [REDACTED]",
    }


def test_links_ssrf_and_secrets(tmp_path: Path) -> None:
    item = service()
    item.service_url = "https://openwebui.home.arpa"
    item.grafana_config = {"dashboard_uid": "containers", "variables": {"service": "open webui"}}
    item.loki_config = {"query": '{service="open-webui"}'}
    item.portainer_environment_id = "1"
    links = resolve_links(
        item,
        "https://portainer.home.arpa",
        "https://grafana.home.arpa",
        "https://loki.home.arpa",
    )
    assert "var-service=open+webui" in links["grafana"] and "portainer" in links
    validate_health_url("https://openwebui.home.arpa/health", (".home.arpa",))
    with pytest.raises(ValidationError):
        validate_health_url("http://127.0.0.1/", (".home.arpa",))
    (tmp_path / "postgres_password").write_text(" value\n")
    assert FileSecretReader(tmp_path).read("postgres_password") == "value"
    with pytest.raises(ConfigurationError):
        FileSecretReader(tmp_path).read("missing")


def test_file_secret_reader_warns_on_overly_permissive_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-039: a secret file readable by group/other should be flagged, not silently accepted."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "capataz_api.infrastructure.secrets.file_secret_reader.logger.warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )
    loose = tmp_path / "loose_secret"
    loose.write_text("value")
    loose.chmod(0o644)
    FileSecretReader(tmp_path).read("loose_secret")
    assert warnings

    warnings.clear()
    strict = tmp_path / "strict_secret"
    strict.write_text("value")
    strict.chmod(0o600)
    FileSecretReader(tmp_path).read("strict_secret")
    assert not warnings


def test_execution_source_matches_the_published_contract() -> None:
    """CR-062: pins ExecutionSource against docs/02-contracts.en.md §6 so a future enum edit that

    drops/misplaces a member (as happened when AggregationMode was introduced) fails CI instead
    of only a 422 in production for e.g. an MCP integration sending source="mcp".
    """
    assert {member.value for member in ExecutionSource} == {
        "ui",
        "api",
        "yaml",
        "n8n",
        "mcp",
        "cron",
        "alert",
        "system",
    }
