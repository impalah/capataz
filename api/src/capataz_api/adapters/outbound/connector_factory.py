"""Builds outbound clients from a connector's config plus its already-decrypted resources."""

from collections.abc import Mapping

from capataz_api.adapters.outbound.health import HttpHealthProber
from capataz_api.adapters.outbound.portainer import PortainerClient
from capataz_api.adapters.outbound.prometheus import PrometheusMetricsProvider
from capataz_api.application.policies import narrow_suffixes
from capataz_api.application.ports import (
    ContainerPlatformPort,
    HealthProbePort,
    MetricsProviderPort,
)
from capataz_api.domain.entities import Connector
from capataz_api.domain.exceptions import ConfigurationError
from capataz_api.domain.specs import HttpConnector, PortainerConnector, PrometheusConnector


class DefaultConnectorClientFactory:
    def __init__(self, global_suffixes: tuple[str, ...], timeout: float) -> None:
        self._global_suffixes, self._timeout = global_suffixes, timeout

    def platform(self, connector: Connector, secrets: Mapping[str, str]) -> ContainerPlatformPort:
        spec = connector.spec
        if not isinstance(spec, PortainerConnector):
            raise ConfigurationError(f"Connector {connector.id!r} is not a Portainer connector")
        return PortainerClient(
            str(spec.config.url), secrets["token"], self._timeout, verify=spec.config.verify_tls
        )

    def metrics(self, connector: Connector, secrets: Mapping[str, str]) -> MetricsProviderPort:
        spec = connector.spec
        if not isinstance(spec, PrometheusConnector):
            raise ConfigurationError(f"Connector {connector.id!r} is not a Prometheus connector")
        return PrometheusMetricsProvider(
            str(spec.config.url),
            secrets.get("token"),
            self._timeout,
            verify=spec.config.verify_tls,
        )

    def prober(self, connector: Connector) -> HealthProbePort:
        spec = connector.spec
        if not isinstance(spec, HttpConnector):
            raise ConfigurationError(f"Connector {connector.id!r} is not an http connector")
        return HttpHealthProber(
            narrow_suffixes(tuple(spec.config.allowed_host_suffixes), self._global_suffixes),
            default_timeout=spec.config.default_timeout_seconds,
            verify=spec.config.verify_tls,
        )
