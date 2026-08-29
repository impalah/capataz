from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from capataz_api.domain.value_objects import ActionType, RiskLevel


class ContainerCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    required: bool = True
    critical: bool = False


class ServiceSelectorCatalog(BaseModel):
    """A Docker Swarm service, matched by ``{stack_name}_{name}`` (Docker's own naming), not by

    a container name — Swarm mangles container names per-task/replica, so exact container-name
    matching (as used for ``ContainerCatalog``) never matches a Swarm-deployed service.
    """

    model_config = ConfigDict(extra="forbid")
    name: str
    replicas: int = Field(default=1, ge=0, le=50)
    required: bool = True
    critical: bool = False


class PortainerCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: str | int
    stack_name: str | None = None
    aggregation: Literal["all_required", "any_healthy"] = "all_required"
    containers: list[ContainerCatalog] | None = None
    services: list[ServiceSelectorCatalog] | None = None

    @model_validator(mode="after")
    def exactly_one_selector_kind(self) -> PortainerCatalog:
        if bool(self.containers) == bool(self.services):
            raise ValueError("portainer requires exactly one of containers or services")
        return self


class HealthCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["http", "tcp"]
    url: HttpUrl
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: int = Field(default=5, ge=1, le=60)


class ActionCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str
    description: str | None = None
    icon: str | None = None
    action_type: ActionType
    risk_level: RiskLevel
    requires_confirmation: bool = False
    enabled: bool = True
    unattended: bool = False
    config: dict[str, Any]
    allowed_parameters_schema: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> ActionCatalog:
        if "command" in self.config:
            raise ValueError("command is never permitted")
        if self.action_type == ActionType.PORTAINER and (
            set(self.config) != {"operation", "target"}
            or self.config.get("operation") not in {"start", "stop", "restart", "logs"}
            or self.config.get("target") not in {"selected_containers", "selected_services"}
        ):
            raise ValueError(
                "Portainer config requires exactly an allowed operation and "
                "a selected_containers/selected_services target"
            )
        if self.action_type == ActionType.ANSIBLE:
            for key in ("playbook", "inventory"):
                path = str(self.config.get(key, ""))
                prefix = "playbooks/" if key == "playbook" else "inventories/"
                if not path.startswith(prefix) or ".." in path:
                    raise ValueError(f"{key} must be an allow-listed relative path")
        return self


class ServiceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str | None = None
    group_name: str
    environment: str
    icon: str | None = None
    service_url: HttpUrl | None = None
    documentation_url: HttpUrl | None = None
    portainer: PortainerCatalog | None = None
    health: HealthCatalog | None = None
    grafana: dict[str, Any] = Field(default_factory=dict)
    loki: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    maintenance: bool = False
    actions: list[ActionCatalog] = Field(default_factory=list)

    @model_validator(mode="after")
    def portainer_action_targets_match_selector_kind(self) -> ServiceCatalog:
        if not self.portainer:
            return self
        expected = "selected_services" if self.portainer.services else "selected_containers"
        for action in self.actions:
            if (
                action.action_type == ActionType.PORTAINER
                and action.config.get("target") != expected
            ):
                raise ValueError(
                    f"action '{action.key}' targets {action.config.get('target')} but "
                    f"portainer declares {'services' if self.portainer.services else 'containers'}"
                )
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    services: list[ServiceCatalog]

    @model_validator(mode="after")
    def unique_services_and_actions(self) -> Catalog:
        ids = [item.id for item in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("service ids must be unique")
        for service in self.services:
            keys = [item.key for item in service.actions]
            if len(keys) != len(set(keys)):
                raise ValueError(f"action keys must be unique for {service.id}")
        return self
