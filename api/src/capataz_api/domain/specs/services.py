"""Service spec: everything that describes a service except its id and its actions."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field, HttpUrl, StringConstraints, field_validator, model_validator

from capataz_api.domain.specs.common import ReferenceId, SpecModel
from capataz_api.domain.value_objects import AggregationMode, ConnectorCapability

Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]


class ContainerSelector(SpecModel):
    name: str = Field(min_length=1, max_length=255)
    required: bool = True
    critical: bool = False


class SwarmServiceSelector(SpecModel):
    """A Docker Swarm service, matched by ``{stack_name}_{name}`` (Docker's own naming) — Swarm
    mangles container names per task/replica, so container-name matching never finds it."""

    name: str = Field(min_length=1, max_length=255)
    replicas: int = Field(default=1, ge=0, le=50)
    required: bool = True
    critical: bool = False


class RuntimeSpec(SpecModel):
    connector: ReferenceId
    environment_id: str = Field(min_length=1, max_length=128)
    stack_name: str | None = Field(default=None, max_length=255)
    aggregation: AggregationMode = AggregationMode.ALL_REQUIRED
    containers: list[ContainerSelector] | None = None
    services: list[SwarmServiceSelector] | None = None

    @field_validator("environment_id", mode="before")
    @classmethod
    def accept_numeric_environment_id(cls, value: Any) -> Any:
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value

    @model_validator(mode="after")
    def exactly_one_selector_kind(self) -> RuntimeSpec:
        if bool(self.containers) == bool(self.services):
            raise ValueError("runtime requires exactly one of containers or services")
        return self

    @property
    def selector_kind(self) -> Literal["containers", "services"]:
        return "services" if self.services else "containers"

    def platform_selectors(self) -> dict[str, Any]:
        """The selector shape ContainerPlatformPort implementations (Portainer) consume."""
        entries = self.services if self.selector_kind == "services" else self.containers
        return {
            self.selector_kind: [entry.model_dump() for entry in entries or []],
            "aggregation": self.aggregation.value,
            "stack_name": self.stack_name,
        }


class HealthSpec(SpecModel):
    connector: ReferenceId
    url: HttpUrl
    method: Literal["GET", "HEAD"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: int = Field(default=5, ge=1, le=60)


class DashboardSpec(SpecModel):
    label: str = Field(default="grafana", min_length=1, max_length=60)
    connector: ReferenceId
    uid: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", max_length=255)
    # Explicit dashboard path (relative to the connector URL) or absolute URL; wins over
    # uid/slug/variables entirely, since the caller has already resolved those.
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def uid_or_url(self) -> DashboardSpec:
        if not (self.uid or self.url):
            raise ValueError("dashboard requires uid or url")
        return self


class LogsSpec(SpecModel):
    connector: ReferenceId
    query: str = Field(min_length=1, max_length=2000)


class MetricSpec(SpecModel):
    """Admin-authored PromQL, run verbatim and read-only (trust boundary: docs/06-security)."""

    label: str = Field(min_length=1, max_length=100)
    connector: ReferenceId
    query: str = Field(min_length=1, max_length=2000)


class ObservabilitySpec(SpecModel):
    health: HealthSpec | None = None
    dashboards: list[DashboardSpec] = Field(default_factory=list)
    logs: LogsSpec | None = None
    metrics: list[MetricSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_dashboard_labels(self) -> ObservabilitySpec:
        labels = [dashboard.label for dashboard in self.dashboards]
        if len(labels) != len(set(labels)):
            raise ValueError("dashboard labels must be unique (they become link names)")
        return self


@dataclass(frozen=True, slots=True)
class ConnectorUsage:
    path: str
    connector_id: str
    capability: ConnectorCapability


class ServiceSpec(SpecModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    group_name: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=128)
    icon: str | None = Field(default=None, max_length=128)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    service_url: HttpUrl | None = None
    documentation_url: HttpUrl | None = None
    runtime: RuntimeSpec | None = None
    observability: ObservabilitySpec = Field(default_factory=ObservabilitySpec)
    metadata: dict[str, Any] = Field(default_factory=dict)
    maintenance: bool = False

    def connector_usages(self) -> list[ConnectorUsage]:
        """Every connector reference in this spec, with the capability it requires."""
        usages: list[ConnectorUsage] = []
        if self.runtime:
            usages.append(
                ConnectorUsage(
                    "runtime.connector", self.runtime.connector, ConnectorCapability.STATUS
                )
            )
        observability = self.observability
        if observability.health:
            usages.append(
                ConnectorUsage(
                    "observability.health.connector",
                    observability.health.connector,
                    ConnectorCapability.HEALTH,
                )
            )
        for index, dashboard in enumerate(observability.dashboards):
            usages.append(
                ConnectorUsage(
                    f"observability.dashboards.{index}.connector",
                    dashboard.connector,
                    ConnectorCapability.DASHBOARDS,
                )
            )
        if observability.logs:
            usages.append(
                ConnectorUsage(
                    "observability.logs.connector",
                    observability.logs.connector,
                    ConnectorCapability.LOGS,
                )
            )
        for index, metric in enumerate(observability.metrics):
            usages.append(
                ConnectorUsage(
                    f"observability.metrics.{index}.connector",
                    metric.connector,
                    ConnectorCapability.METRICS,
                )
            )
        return usages
