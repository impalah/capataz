from pathlib import Path
from uuid import uuid4

import pytest
from fakes import (
    FakeConnectorFactory,
    FakeMetrics,
    FakePlatform,
    FakeProber,
    InMemoryServiceRepository,
    ansible_connector,
    grafana_connector,
    loki_connector,
    make_action,
    make_cipher,
    make_service,
    portainer_connector,
    prometheus_connector,
    runtime,
    seed_connectors,
    ssh_connector,
)

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
from capataz_api.application.services import ConnectorResolver, StatusService
from capataz_api.domain.entities import Execution, Principal, Service
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

HEALTH = {"connector": "http", "url": "https://openwebui.home.arpa/health"}


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


# --- StatusService --------------------------------------------------------------------------------


async def _refresh(
    service: Service, factory: FakeConnectorFactory, repo: InMemoryServiceRepository | None = None
) -> dict[str, object]:
    if repo is None:
        repo = InMemoryServiceRepository()
        seed_connectors(repo)
    return await StatusService(factory).refresh(service, ConnectorResolver(repo, make_cipher()))


@pytest.mark.asyncio
async def test_status_service_refreshes_through_the_runtime_and_health_connectors() -> None:
    platform = FakePlatform(rows=[{"name": "open-webui", "running": True, "healthy": True}])
    prober = FakeProber(healthy=True)
    factory = FakeConnectorFactory(platform=platform, prober=prober)
    item = make_service(runtime=runtime(), observability={"health": HEALTH})

    result = await _refresh(item, factory)

    assert result["status"] == "healthy"
    assert result["service_id"] == "open-webui"
    assert platform.calls == [
        (
            "7",
            {
                "containers": [{"name": "open-webui", "required": True, "critical": False}],
                "aggregation": "all_required",
                "stack_name": None,
            },
        )
    ]
    # The portainer token resource was decrypted and stripped of its trailing newline.
    assert factory.secrets_seen == [{"token": "pt-secret"}]
    assert prober.configs == [
        {
            "connector": "http",
            "url": "https://openwebui.home.arpa/health",
            "method": "GET",
            "expected_status": 200,
            "timeout_seconds": 5,
        }
    ]


@pytest.mark.asyncio
async def test_status_service_surfaces_portainer_failure_without_hiding_health_probe() -> None:
    factory = FakeConnectorFactory(
        platform=FakePlatform(error=ExternalServiceError("Portainer authentication was rejected"))
    )
    item = make_service(runtime=runtime(), observability={"health": HEALTH})
    result = await _refresh(item, factory)
    assert result["error"] == "Portainer authentication was rejected"
    assert result["external_healthy"] is True
    assert result["containers"] == []


@pytest.mark.asyncio
async def test_status_service_reports_unexpected_errors_without_leaking_internals() -> None:
    factory = FakeConnectorFactory(platform=FakePlatform(error=RuntimeError("boom: /internal")))
    result = await _refresh(make_service(runtime=runtime()), factory)
    assert result["error"] == "Unexpected error checking Portainer status"
    assert "boom" not in str(result["error"])


@pytest.mark.asyncio
async def test_status_service_reports_a_missing_connector_or_resource_as_unavailable() -> None:
    missing_connector = await _refresh(
        make_service(runtime=runtime(connector="ghost")), FakeConnectorFactory()
    )
    assert missing_connector["status"] == "unknown"
    assert missing_connector["error"] == "Connector 'ghost' does not exist"

    repo = InMemoryServiceRepository()
    seed_connectors(repo)
    del repo.resources["portainer_token"]
    missing_resource = await _refresh(make_service(runtime=runtime()), FakeConnectorFactory(), repo)
    assert "Resource 'portainer_token'" in str(missing_resource["error"])


@pytest.mark.asyncio
async def test_status_service_includes_metrics_when_the_service_declares_them() -> None:
    factory = FakeConnectorFactory(metrics=FakeMetrics(value=42.0))
    item = make_service(
        observability={"metrics": [{"label": "CPU", "connector": "prometheus", "query": "up"}]}
    )
    result = await _refresh(item, factory)
    assert result["metrics"] == [{"label": "CPU", "value": 42.0}]


@pytest.mark.asyncio
async def test_status_service_omits_metrics_key_when_the_service_declares_none() -> None:
    result = await _refresh(
        make_service(), FakeConnectorFactory(metrics=FakeMetrics(error=AssertionError()))
    )
    assert "metrics" not in result


@pytest.mark.asyncio
async def test_a_failing_metrics_connector_only_blanks_its_own_metrics() -> None:
    repo = InMemoryServiceRepository()
    seed_connectors(repo)
    repo.connectors["prom_broken"] = prometheus_connector("prom_broken")
    factory = FakeConnectorFactory(
        platform=FakePlatform(rows=[{"name": "open-webui", "running": True, "healthy": True}]),
        metrics={
            "prometheus": FakeMetrics(value=7.0),
            "prom_broken": FakeMetrics(error=RuntimeError("Prometheus is unreachable")),
        },
    )
    item = make_service(
        runtime=runtime(),
        observability={
            "metrics": [
                {"label": "CPU", "connector": "prometheus", "query": "cpu"},
                {"label": "GPU", "connector": "prom_broken", "query": "gpu"},
                {"label": "Mem", "connector": "prometheus", "query": "mem"},
            ]
        },
    )

    result = await _refresh(item, factory, repo)

    assert result["status"] == "healthy"
    assert result["metrics"] == [
        {"label": "CPU", "value": 7.0},
        {"label": "GPU", "value": None},
        {"label": "Mem", "value": 7.0},
    ]
    # Metrics on the same connector go out in one provider call, in declaration order.
    assert [
        [d["query"] for d in batch] for batch in factory.metrics_fakes["prometheus"].queries
    ] == [["cpu", "mem"]]


# --- resolve_action -------------------------------------------------------------------------------


def _containers_service() -> Service:
    return make_service(runtime=runtime())


def test_rbac_risk_and_allowlisted_action_resolution() -> None:
    operator = Principal("op", {ROLE_OPERATOR})
    admin = Principal("admin", {ROLE_ADMIN})
    authorize_action(operator, RiskLevel.OPERATE, False, None)
    with pytest.raises(AuthorizationError):
        authorize_action(operator, RiskLevel.CRITICAL, True, "reason")
    with pytest.raises(AuthorizationError):
        authorize_action(admin, RiskLevel.CRITICAL, True, None)
    action = make_action(allowed_parameters_schema={"properties": {"mode": {"enum": ["safe"]}}})
    resolved = resolve_action(
        _containers_service(), action, {"mode": "safe"}, portainer_connector()
    )
    assert resolved["config"]["operation"] == "restart"
    with pytest.raises(ValidationError):
        resolve_action(
            _containers_service(), action, {"container_id": "untrusted"}, portainer_connector()
        )


def test_resolve_action_rejects_extra_portainer_keys_and_distinguishes_errors() -> None:
    extra = make_action(
        config={"operation": "restart", "target": "selected_containers", "extra": "nope"}
    )
    with pytest.raises(ValidationError, match="Invalid action config"):
        resolve_action(_containers_service(), extra, {}, portainer_connector())

    with pytest.raises(ValidationError, match="not enabled"):
        resolve_action(_containers_service(), make_action(enabled=False), {}, portainer_connector())

    with pytest.raises(ValidationError, match="does not belong to this service"):
        resolve_action(
            _containers_service(),
            make_action(service_id="other-service"),
            {},
            portainer_connector(),
        )


def test_resolve_action_accepts_selected_services_for_a_swarm_service() -> None:
    swarm = make_service(
        "authentik",
        runtime=runtime(kind="services", names=("authentik-server",), stack_name="authentik"),
    )
    action = make_action(
        "authentik", config={"operation": "restart", "target": "selected_services"}
    )
    resolved = resolve_action(swarm, action, {}, portainer_connector())
    assert resolved["config"]["target"] == "selected_services"

    mismatched = make_action("authentik")
    with pytest.raises(ValidationError, match="declared selector kind"):
        resolve_action(swarm, mismatched, {}, portainer_connector())


def test_portainer_actions_must_use_the_services_runtime_connector() -> None:
    action = make_action(connector_id="portainer_other")
    with pytest.raises(ValidationError, match="runtime connector"):
        resolve_action(_containers_service(), action, {}, portainer_connector("portainer_other"))


def test_resolve_action_rejects_type_and_capability_mismatches() -> None:
    with pytest.raises(ValidationError, match="does not match its connector type"):
        resolve_action(
            _containers_service(),
            make_action(action_type=ActionType.ANSIBLE),
            {},
            portainer_connector(),
        )
    with pytest.raises(ValidationError, match="does not support actions"):
        resolve_action(
            _containers_service(),
            make_action(connector_id="grafana"),
            {},
            grafana_connector(),
        )
    with pytest.raises(ValidationError, match="does not match the action definition"):
        resolve_action(_containers_service(), make_action(), {}, ssh_connector())


def test_ssh_and_ansible_actions_only_accept_their_own_config_shapes() -> None:
    ssh_action = make_action(
        key="disk",
        connector_id="ssh_mole",
        action_type=ActionType.SSH,
        config={"command_id": "disk_usage", "params": {"path": "/srv"}},
    )
    resolved = resolve_action(_containers_service(), ssh_action, {}, ssh_connector())
    assert resolved["config"] == {"command_id": "disk_usage", "params": {"path": "/srv"}}

    free_text = make_action(
        key="disk",
        connector_id="ssh_mole",
        action_type=ActionType.SSH,
        config={"command_id": "ping -c 4 host"},
    )
    with pytest.raises(ValidationError, match="Invalid action config"):
        resolve_action(_containers_service(), free_text, {}, ssh_connector())

    ansible_action = make_action(
        key="backup",
        connector_id="ansible_homelab",
        action_type=ActionType.ANSIBLE,
        config={"playbook": "playbooks/backup_service.yml", "limit": "node-ai-01"},
    )
    resolved = resolve_action(_containers_service(), ansible_action, {}, ansible_connector())
    assert resolved["config"]["timeout_seconds"] == 300


# --- misc domain behaviour ----------------------------------------------------------------------


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


# --- links ----------------------------------------------------------------------------------------


def _connectors(*extra: object) -> dict[str, object]:
    items = [portainer_connector(), grafana_connector(), loki_connector(), *extra]
    return {item.id: item for item in items}  # type: ignore[attr-defined]


def test_links_are_built_from_the_referenced_connectors() -> None:
    item = make_service(
        service_url="https://openwebui.home.arpa",
        runtime=runtime(environment_id="1"),
        observability={
            "dashboards": [
                {
                    "connector": "grafana",
                    "uid": "containers",
                    "variables": {"var-service": "open webui"},
                }
            ],
            "logs": {"connector": "loki", "query": '{service="open-webui"}'},
        },
    )
    links = resolve_links(item, _connectors())  # type: ignore[arg-type]
    assert links["service"] == "https://openwebui.home.arpa/"
    assert links["grafana"] == "https://grafana.home.arpa/d/containers?var-service=open+webui"
    assert links["portainer"] == "https://portainer.home.arpa/#!/1/docker/containers"
    assert links["loki"].startswith("https://loki.home.arpa/explore?left=")

    swarm = make_service(runtime=runtime(kind="services", names=("authentik-server",)))
    assert resolve_links(swarm, _connectors())["portainer"].endswith("/docker/services")  # type: ignore[arg-type]


def test_grafana_link_uses_uid_slug_and_extra_query_params() -> None:
    item = make_service(
        observability={
            "dashboards": [
                {
                    "connector": "grafana",
                    "uid": "homelab-generic",
                    "slug": "generic-service",
                    "variables": {"var-service": "bifrost", "kiosk": "tv"},
                }
            ]
        }
    )
    assert resolve_links(item, _connectors())["grafana"] == (  # type: ignore[arg-type]
        "https://grafana.home.arpa/d/homelab-generic/generic-service?var-service=bifrost&kiosk=tv"
    )


def test_each_dashboard_is_keyed_by_label_and_can_use_its_own_grafana() -> None:
    alt = grafana_connector("grafana_gpu", url="https://grafana-gpu.home.arpa")
    item = make_service(
        observability={
            "dashboards": [
                {"connector": "grafana", "uid": "containers"},
                {"label": "GPU", "connector": "grafana_gpu", "uid": "gpu"},
            ]
        }
    )
    links = resolve_links(item, _connectors(alt))  # type: ignore[arg-type]
    assert links["grafana"] == "https://grafana.home.arpa/d/containers"
    assert links["GPU"] == "https://grafana-gpu.home.arpa/d/gpu"


def test_grafana_link_prefers_an_explicit_url_over_uid_and_variables() -> None:
    absolute = make_service(
        observability={
            "dashboards": [
                {
                    "connector": "grafana",
                    "uid": "ignored",
                    "variables": {"var-service": "ignored"},
                    "url": "https://grafana.home.arpa/d/containers/x?kiosk=tv",
                }
            ]
        }
    )
    relative = make_service(
        observability={"dashboards": [{"connector": "grafana", "url": "d/containers/x?kiosk=tv"}]}
    )
    expected = "https://grafana.home.arpa/d/containers/x?kiosk=tv"
    assert resolve_links(absolute, _connectors())["grafana"] == expected  # type: ignore[arg-type]
    assert resolve_links(relative, _connectors())["grafana"] == expected  # type: ignore[arg-type]


def test_links_skip_missing_or_wrongly_typed_connectors() -> None:
    item = make_service(
        runtime=runtime(connector="ghost"),
        observability={"dashboards": [{"connector": "loki", "uid": "x"}]},
    )
    assert resolve_links(item, _connectors()) == {}  # type: ignore[arg-type]


def test_ssrf_validation_and_file_secrets(tmp_path: Path) -> None:
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
