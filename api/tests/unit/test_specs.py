"""Unit tests for domain/specs: resources, connectors (plugins), actions and services."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from capataz_api.domain.specs import (
    CONNECTOR_SPEC_ADAPTER,
    MAX_RESOURCE_BYTES,
    ActionSpec,
    EnvSource,
    FileSource,
    InlineSource,
    PortainerConnector,
    ResourceSpec,
    ServiceSpec,
    connector_capabilities,
    connector_resource_refs,
    connector_type,
    validate_action_config,
)
from capataz_api.domain.value_objects import ConnectorCapability, ConnectorType, ResourceType

# --- resources -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"file": "ssh_mole_key"}, FileSource),
        ({"file": "keys/mole.pem"}, FileSource),
        ({"env": "SSH_MOLE_KEY_B64", "encoding": "base64"}, EnvSource),
        ({"base64": base64.b64encode(b"token").decode()}, InlineSource),
    ],
)
def test_resource_source_forms(source: dict[str, str], expected: type) -> None:
    spec = ResourceSpec.model_validate({"id": "ssh_mole_key", "type": "secret", "source": source})
    assert isinstance(spec.source, expected)


@pytest.mark.parametrize(
    "path", ["/etc/shadow", "../secrets/database_url", "keys/../../database_url", ".hidden"]
)
def test_file_source_rejects_absolute_and_traversal_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        ResourceSpec.model_validate({"id": "k", "type": "secret", "source": {"file": path}})


def test_inline_source_rejects_invalid_base64() -> None:
    with pytest.raises(ValidationError, match="not valid base64"):
        InlineSource(base64="***not base64***")


def test_inline_source_rejects_oversized_content() -> None:
    too_big = base64.b64encode(b"x" * (MAX_RESOURCE_BYTES + 1)).decode()
    with pytest.raises(ValidationError, match="exceeds"):
        InlineSource(base64=too_big)


def test_inline_source_accepts_base64_folded_over_lines() -> None:
    encoded = base64.b64encode(b"a-longer-private-key-body").decode()
    folded = f"{encoded[:10]}\n  {encoded[10:]}\n"
    assert InlineSource(base64=folded).base64 == encoded


def test_resource_without_source_is_valid_for_ui_uploaded_resources() -> None:
    assert ResourceSpec.model_validate({"id": "k", "type": "known_hosts"}).source is None


def test_unknown_resource_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ResourceSpec.model_validate({"id": "k", "type": "password_manager"})


# --- connectors ----------------------------------------------------------------------------


def test_connector_union_is_discriminated_by_type() -> None:
    connector = CONNECTOR_SPEC_ADAPTER.validate_python(
        {
            "id": "portainer_main",
            "type": "portainer",
            "config": {"url": "https://portainer.404labo.net", "token": "portainer_token"},
        }
    )
    assert isinstance(connector, PortainerConnector)
    assert connector_type(connector) is ConnectorType.PORTAINER
    assert connector_capabilities(connector) == {
        ConnectorCapability.STATUS,
        ConnectorCapability.ACTIONS,
    }
    assert connector_resource_refs(connector) == {"token": ("portainer_token", ResourceType.SECRET)}


def test_unknown_connector_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CONNECTOR_SPEC_ADAPTER.validate_python({"id": "x", "type": "kubernetes", "config": {}})


def test_connector_config_rejects_fields_of_another_type() -> None:
    with pytest.raises(ValidationError):
        CONNECTOR_SPEC_ADAPTER.validate_python(
            {"id": "g", "type": "grafana", "config": {"url": "https://g.404labo.net", "token": "t"}}
        )


def test_optional_resource_refs_are_omitted_when_unset() -> None:
    connector = CONNECTOR_SPEC_ADAPTER.validate_python(
        {"id": "prom", "type": "prometheus", "config": {"url": "http://prometheus:9090"}}
    )
    assert connector_resource_refs(connector) == {}


def test_ansible_connector_requires_an_allow_listed_inventory_path() -> None:
    base = {"private_key": "k", "known_hosts": "kh"}
    ok = CONNECTOR_SPEC_ADAPTER.validate_python(
        {"id": "a", "type": "ansible", "config": {**base, "inventory": "inventories/homelab.yml"}}
    )
    assert connector_resource_refs(ok) == {
        "private_key": ("k", ResourceType.SSH_PRIVATE_KEY),
        "known_hosts": ("kh", ResourceType.KNOWN_HOSTS),
    }
    with pytest.raises(ValidationError):
        CONNECTOR_SPEC_ADAPTER.validate_python(
            {"id": "a", "type": "ansible", "config": {**base, "inventory": "/etc/ansible/hosts"}}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("host", "mole.404labo.net; rm -rf /"), ("host", "-oProxyCommand=x"), ("user", "root;id")],
)
def test_ssh_connector_rejects_injection_shaped_host_and_user(field: str, value: str) -> None:
    config = {
        "host": "mole.404labo.net",
        "user": "capataz",
        "private_key": "k",
        "known_hosts": "kh",
    }
    config[field] = value
    with pytest.raises(ValidationError):
        CONNECTOR_SPEC_ADAPTER.validate_python({"id": "s", "type": "ssh", "config": config})


def test_http_connector_rejects_malformed_host_suffixes() -> None:
    with pytest.raises(ValidationError):
        CONNECTOR_SPEC_ADAPTER.validate_python(
            {"id": "h", "type": "http", "config": {"allowed_host_suffixes": ["*.evil.com"]}}
        )


# --- actions -------------------------------------------------------------------------------


def test_portainer_action_config_is_validated_against_its_connector_type() -> None:
    assert validate_action_config(
        ConnectorType.PORTAINER, {"operation": "restart", "target": "selected_services"}
    ) == {"operation": "restart", "target": "selected_services"}
    with pytest.raises(ValueError):
        validate_action_config(ConnectorType.PORTAINER, {"operation": "rm", "target": "x"})


def test_action_config_never_permits_a_command_field() -> None:
    with pytest.raises(ValueError, match="command is never permitted"):
        validate_action_config(ConnectorType.SSH, {"command_id": "ping", "command": "id"})
    with pytest.raises(ValidationError, match="command is never permitted"):
        ActionSpec.model_validate(
            {
                "key": "x",
                "label": "X",
                "risk_level": "read",
                "connector": "ssh_mole",
                "config": {"command": "id"},
            }
        )


def test_ssh_action_config_only_accepts_a_command_id_slug() -> None:
    assert validate_action_config(
        ConnectorType.SSH, {"command_id": "disk_usage", "params": {"path": "/srv"}}
    ) == {"command_id": "disk_usage", "params": {"path": "/srv"}}
    with pytest.raises(ValueError):
        validate_action_config(ConnectorType.SSH, {"command_id": "ping -c 4 host"})


def test_ansible_action_config_rejects_playbook_traversal() -> None:
    with pytest.raises(ValueError):
        validate_action_config(
            ConnectorType.ANSIBLE, {"playbook": "playbooks/../../etc.yml", "limit": "node-ai-01"}
        )


def test_connector_types_without_actions_capability_reject_actions() -> None:
    with pytest.raises(ValueError, match="does not support actions"):
        validate_action_config(ConnectorType.GRAFANA, {})


def test_unknown_risk_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ActionSpec.model_validate(
            {"key": "x", "label": "X", "risk_level": "low", "connector": "c", "config": {}}
        )


# --- services ------------------------------------------------------------------------------


def _service(**overrides: object) -> dict[str, object]:
    return {"name": "Open WebUI", "group_name": "IA", "environment": "homelab", **overrides}


def test_runtime_requires_exactly_one_selector_kind_and_accepts_numeric_environment_id() -> None:
    spec = ServiceSpec.model_validate(
        _service(
            runtime={
                "connector": "portainer_main",
                "environment_id": 7,
                "services": [{"name": "open-webui"}],
            }
        )
    )
    assert spec.runtime is not None
    assert spec.runtime.environment_id == "7"
    assert spec.runtime.selector_kind == "services"
    with pytest.raises(ValidationError, match="exactly one of containers or services"):
        ServiceSpec.model_validate(_service(runtime={"connector": "p", "environment_id": "7"}))


def test_dashboard_requires_uid_or_url_and_labels_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="uid or url"):
        ServiceSpec.model_validate(
            _service(observability={"dashboards": [{"connector": "grafana"}]})
        )
    with pytest.raises(ValidationError, match="labels must be unique"):
        ServiceSpec.model_validate(
            _service(
                observability={
                    "dashboards": [
                        {"connector": "grafana", "uid": "a"},
                        {"connector": "grafana", "uid": "b"},
                    ]
                }
            )
        )


def test_tags_must_be_slugs() -> None:
    assert ServiceSpec.model_validate(_service(tags=["local", "gpu_1"])).tags == ["local", "gpu_1"]
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate(_service(tags=["Not A Tag"]))


def test_connector_usages_lists_every_reference_with_its_required_capability() -> None:
    spec = ServiceSpec.model_validate(
        _service(
            runtime={
                "connector": "portainer_main",
                "environment_id": "7",
                "containers": [{"name": "app"}],
            },
            observability={
                "health": {"connector": "http", "url": "https://app.404labo.net/health"},
                "dashboards": [{"connector": "grafana", "uid": "d"}],
                "logs": {"connector": "loki", "query": '{app="x"}'},
                "metrics": [{"label": "CPU", "connector": "prometheus", "query": "up"}],
            },
        )
    )
    assert [(u.path, u.connector_id, u.capability) for u in spec.connector_usages()] == [
        ("runtime.connector", "portainer_main", ConnectorCapability.STATUS),
        ("observability.health.connector", "http", ConnectorCapability.HEALTH),
        ("observability.dashboards.0.connector", "grafana", ConnectorCapability.DASHBOARDS),
        ("observability.logs.connector", "loki", ConnectorCapability.LOGS),
        ("observability.metrics.0.connector", "prometheus", ConnectorCapability.METRICS),
    ]


def test_service_spec_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate(_service(portainer={"environment_id": 7}))
