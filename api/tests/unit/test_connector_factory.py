"""adapters/outbound/connector_factory.py: clients built from connector config + secrets."""

from __future__ import annotations

import pytest
from fakes import grafana_connector, make_connector, portainer_connector, prometheus_connector

from capataz_api.adapters.outbound.connector_factory import DefaultConnectorClientFactory
from capataz_api.adapters.outbound.health import HttpHealthProber
from capataz_api.adapters.outbound.portainer import PortainerClient
from capataz_api.adapters.outbound.prometheus import PrometheusMetricsProvider
from capataz_api.domain.exceptions import ConfigurationError

FACTORY = DefaultConnectorClientFactory((".home.arpa",), 5)


def test_platform_is_a_portainer_client_with_the_decrypted_token() -> None:
    client = FACTORY.platform(portainer_connector(), {"token": "pt"})
    assert isinstance(client, PortainerClient)
    assert (client.base_url, client.token, client.verify) == (
        "https://portainer.home.arpa",
        "pt",
        True,
    )


def test_metrics_provider_token_is_optional() -> None:
    provider = FACTORY.metrics(prometheus_connector(), {})
    assert isinstance(provider, PrometheusMetricsProvider)
    assert provider.token is None
    assert provider.base_url == "https://prometheus.home.arpa"


def test_prober_narrows_the_global_allow_list_and_never_widens_it() -> None:
    narrowed = FACTORY.prober(
        make_connector(
            "h",
            "http",
            allowed_host_suffixes=[".lab.home.arpa", ".example.com"],
            default_timeout_seconds=9,
            verify_tls=False,
        )
    )
    assert isinstance(narrowed, HttpHealthProber)
    assert narrowed.allowed_suffixes == (".lab.home.arpa",)
    assert (narrowed.default_timeout, narrowed.verify) == (9, False)
    assert FACTORY.prober(make_connector("h", "http")).allowed_suffixes == (".home.arpa",)


def test_connectors_of_the_wrong_type_are_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        FACTORY.platform(grafana_connector(), {})
    with pytest.raises(ConfigurationError):
        FACTORY.metrics(portainer_connector(), {})
    with pytest.raises(ConfigurationError):
        FACTORY.prober(prometheus_connector())
