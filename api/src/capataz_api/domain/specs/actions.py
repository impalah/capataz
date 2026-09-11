"""Action specs. An action's ``config`` shape depends on the type of the connector it uses."""

from typing import Any, Literal

from pydantic import Field, field_validator

from capataz_api.domain.specs.common import ReferenceId, SpecModel
from capataz_api.domain.value_objects import ConnectorType, RiskLevel

# Mirrors the runner's SAFE_SLUG (runner/src/capataz_runner/actions.py), which stays the
# authoritative allow-list; this is only an early, friendlier rejection at save time.
SAFE_SLUG_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$"


def _reject_command(config: dict[str, Any]) -> dict[str, Any]:
    if "command" in config:
        raise ValueError("command is never permitted")
    return config


class PortainerActionConfig(SpecModel):
    operation: Literal["start", "stop", "restart", "logs"]
    target: Literal["selected_containers", "selected_services"]


class AnsibleActionConfig(SpecModel):
    playbook: str = Field(pattern=r"^playbooks/[A-Za-z0-9_-]+\.ya?ml$")
    limit: str = Field(pattern=SAFE_SLUG_PATTERN)
    extra_vars: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=900)


class SshActionConfig(SpecModel):
    # Only an id into runner/ssh_commands.yml (versioned in the repo) — never command text.
    command_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    params: dict[str, str] = Field(default_factory=dict)


ACTION_CONFIG_MODELS: dict[ConnectorType, type[SpecModel]] = {
    ConnectorType.PORTAINER: PortainerActionConfig,
    ConnectorType.ANSIBLE: AnsibleActionConfig,
    ConnectorType.SSH: SshActionConfig,
}


def validate_action_config(connector_type: ConnectorType, config: dict[str, Any]) -> dict[str, Any]:
    """Validate an action config against its connector type; returns the normalized config.

    Raises ValueError (pydantic's ValidationError is one) for any shape the type doesn't allow.
    """
    _reject_command(config)
    model = ACTION_CONFIG_MODELS.get(connector_type)
    if model is None:
        raise ValueError(f"connector type {connector_type.value} does not support actions")
    return model.model_validate(config).model_dump(mode="json")


class ActionSpec(SpecModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=128)
    label: str = Field(min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=128)
    risk_level: RiskLevel
    requires_confirmation: bool = False
    enabled: bool = True
    unattended: bool = False
    connector: ReferenceId
    config: dict[str, Any]
    allowed_parameters_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def config_never_carries_a_command(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_command(value)
