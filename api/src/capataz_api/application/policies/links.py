"""Pure link-building for external tools; no I/O, so it belongs in application, not outbound."""

from collections.abc import Iterator, Mapping
from urllib.parse import quote, urlencode

from capataz_api.domain.entities import Connector, Service
from capataz_api.domain.specs import (
    DashboardSpec,
    GrafanaConnector,
    LokiConnector,
    PortainerConnector,
)
from capataz_api.domain.specs.services import ServiceSpec


def _base(url: object) -> str:
    return str(url).rstrip("/")


def _service_links(spec: ServiceSpec) -> dict[str, str]:
    links: dict[str, str] = {}
    if spec.service_url:
        links["service"] = str(spec.service_url)
    if spec.documentation_url:
        links["documentation"] = str(spec.documentation_url)
    return links


def _portainer_link(spec: ServiceSpec, connectors: Mapping[str, Connector]) -> dict[str, str]:
    runtime = spec.runtime
    if runtime is None:
        return {}
    connector = connectors.get(runtime.connector)
    if connector is None or not isinstance(connector.spec, PortainerConnector):
        return {}
    path = f"#!/{runtime.environment_id}/docker/{runtime.selector_kind}"
    return {"portainer": f"{_base(connector.spec.config.url)}/{path}"}


def _dashboard_path(dashboard: DashboardSpec) -> str:
    """The `d/{uid}[/{slug}]?{variables}` path for a uid-based dashboard (no explicit `url`)."""
    # safe="/" lets a legacy uid still carry a folder path without Grafana rejecting %2F.
    path = f"d/{quote(str(dashboard.uid), safe='/')}"
    if dashboard.slug:
        path = f"{path}/{dashboard.slug}"
    # Variables pass through verbatim (not auto-prefixed with "var-") so a service can also set
    # non-variable query params Grafana recognizes, e.g. kiosk=tv.
    suffix = f"?{urlencode(dashboard.variables)}" if dashboard.variables else ""
    return f"{path}{suffix}"


def _dashboard_link(
    dashboard: DashboardSpec, connectors: Mapping[str, Connector]
) -> tuple[str, str] | None:
    connector = connectors.get(dashboard.connector)
    if connector is None or not isinstance(connector.spec, GrafanaConnector):
        return None
    base = _base(connector.spec.config.url)
    if not dashboard.url:
        return dashboard.label, f"{base}/{_dashboard_path(dashboard)}"
    # An explicit url is the full, final path (or already-absolute URL): it wins over
    # uid/slug/variables entirely, since the caller has already resolved those.
    if dashboard.url.startswith(("http://", "https://")):
        return dashboard.label, dashboard.url
    return dashboard.label, f"{base}/{dashboard.url.lstrip('/')}"


def _resolved_dashboard_links(
    spec: ServiceSpec, connectors: Mapping[str, Connector]
) -> Iterator[tuple[str, str]]:
    for dashboard in spec.observability.dashboards:
        link = _dashboard_link(dashboard, connectors)
        if link is not None:
            yield link


def _dashboard_links(spec: ServiceSpec, connectors: Mapping[str, Connector]) -> dict[str, str]:
    """Keyed by each dashboard's label (default "grafana")."""
    return dict(_resolved_dashboard_links(spec, connectors))


def _loki_link(spec: ServiceSpec, connectors: Mapping[str, Connector]) -> dict[str, str]:
    logs = spec.observability.logs
    if logs is None:
        return {}
    connector = connectors.get(logs.connector)
    if connector is None or not isinstance(connector.spec, LokiConnector):
        return {}
    url = f"{_base(connector.spec.config.url)}/explore?{urlencode({'left': logs.query})}"
    return {"loki": url}


def resolve_links(service: Service, connectors: Mapping[str, Connector]) -> dict[str, str]:
    """Deep links keyed by name; each dashboard is keyed by its label (default "grafana")."""
    spec = service.spec
    return {
        **_service_links(spec),
        **_portainer_link(spec, connectors),
        **_dashboard_links(spec, connectors),
        **_loki_link(spec, connectors),
    }
