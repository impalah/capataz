"""Connector specs: typed connection plugins for service status, observability and actions.

Each connector type is one model of the ``ConnectorSpec`` discriminated union, and declares two
things that make it a plugin: ``CAPABILITIES`` (what a service may reference it for) and its
config's ``RESOURCE_FIELDS`` (which config fields name an encrypted resource, and of which type).
"""

from typing import Annotated, ClassVar, Literal

from pydantic import Field, HttpUrl, TypeAdapter, field_validator

from capataz_api.domain.specs.common import ReferenceId, SpecModel
from capataz_api.domain.value_objects import ConnectorCapability, ConnectorType, ResourceType

HOSTNAME_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
HOST_SUFFIX_PATTERN = r"^\.?[a-z0-9]([a-z0-9.-]*[a-z0-9])?$"
POSIX_USER_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"

HostSuffix = Annotated[str, Field(pattern=HOST_SUFFIX_PATTERN, max_length=253)]


class ConnectorConfig(SpecModel):
    RESOURCE_FIELDS: ClassVar[dict[str, ResourceType]] = {}


class PortainerConfig(ConnectorConfig):
    RESOURCE_FIELDS: ClassVar[dict[str, ResourceType]] = {"token": ResourceType.SECRET}
    url: HttpUrl
    token: ReferenceId
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def https_only(cls, value: HttpUrl) -> HttpUrl:
        # The admin-level API token travels on every request (API status checks and runner
        # actions alike), so it must never go over plain HTTP.
        if value.scheme != "https":
            raise ValueError("Portainer URL must use https")
        return value


class PrometheusConfig(ConnectorConfig):
    RESOURCE_FIELDS: ClassVar[dict[str, ResourceType]] = {"token": ResourceType.SECRET}
    url: HttpUrl
    token: ReferenceId | None = None
    verify_tls: bool = True


class GrafanaConfig(ConnectorConfig):
    url: HttpUrl


class LokiConfig(ConnectorConfig):
    url: HttpUrl


class HttpConfig(ConnectorConfig):
    # Can only narrow CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES (the global ceiling), never widen it;
    # empty means "inherit the global allow-list as is".
    allowed_host_suffixes: list[HostSuffix] = Field(default_factory=list)
    verify_tls: bool = True
    default_timeout_seconds: int = Field(default=5, ge=1, le=60)


class AnsibleConfig(ConnectorConfig):
    RESOURCE_FIELDS: ClassVar[dict[str, ResourceType]] = {
        "private_key": ResourceType.SSH_PRIVATE_KEY,
        "known_hosts": ResourceType.KNOWN_HOSTS,
        "vault_password": ResourceType.SECRET,
    }
    inventory: str = Field(pattern=r"^inventories/[A-Za-z0-9_-]+\.ya?ml$")
    user: str | None = Field(default=None, pattern=POSIX_USER_PATTERN)
    private_key: ReferenceId
    known_hosts: ReferenceId
    vault_password: ReferenceId | None = None


class SshConfig(ConnectorConfig):
    RESOURCE_FIELDS: ClassVar[dict[str, ResourceType]] = {
        "private_key": ResourceType.SSH_PRIVATE_KEY,
        "known_hosts": ResourceType.KNOWN_HOSTS,
    }
    host: str = Field(pattern=HOSTNAME_PATTERN, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    user: str = Field(pattern=POSIX_USER_PATTERN)
    private_key: ReferenceId
    known_hosts: ReferenceId


class ConnectorBase(SpecModel):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset()
    id: ReferenceId
    description: str | None = Field(default=None, max_length=500)


class PortainerConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset(
        {ConnectorCapability.STATUS, ConnectorCapability.ACTIONS}
    )
    type: Literal["portainer"]
    config: PortainerConfig


class PrometheusConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset(
        {ConnectorCapability.METRICS}
    )
    type: Literal["prometheus"]
    config: PrometheusConfig


class GrafanaConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset(
        {ConnectorCapability.DASHBOARDS}
    )
    type: Literal["grafana"]
    config: GrafanaConfig


class LokiConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset({ConnectorCapability.LOGS})
    type: Literal["loki"]
    config: LokiConfig


class HttpConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset({ConnectorCapability.HEALTH})
    type: Literal["http"]
    # Every http setting is optional, so `{id: http, type: http}` alone is a valid connector.
    config: HttpConfig = Field(default_factory=HttpConfig)


class AnsibleConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset(
        {ConnectorCapability.ACTIONS}
    )
    type: Literal["ansible"]
    config: AnsibleConfig


class SshConnector(ConnectorBase):
    CAPABILITIES: ClassVar[frozenset[ConnectorCapability]] = frozenset(
        {ConnectorCapability.ACTIONS}
    )
    type: Literal["ssh"]
    config: SshConfig


ConnectorSpec = Annotated[
    PortainerConnector
    | PrometheusConnector
    | GrafanaConnector
    | LokiConnector
    | HttpConnector
    | AnsibleConnector
    | SshConnector,
    Field(discriminator="type"),
]

CONNECTOR_SPEC_ADAPTER: TypeAdapter[ConnectorSpec] = TypeAdapter(ConnectorSpec)


def connector_type(connector: ConnectorSpec) -> ConnectorType:
    return ConnectorType(connector.type)


def connector_capabilities(connector: ConnectorSpec) -> frozenset[ConnectorCapability]:
    return type(connector).CAPABILITIES


def connector_resource_refs(connector: ConnectorSpec) -> dict[str, tuple[str, ResourceType]]:
    """Config field name -> (referenced resource id, expected resource type), set fields only."""
    config = connector.config
    refs: dict[str, tuple[str, ResourceType]] = {}
    for field_name, resource_type in type(config).RESOURCE_FIELDS.items():
        value = getattr(config, field_name)
        if value is not None:
            refs[field_name] = (str(value), resource_type)
    return refs
