"""Pure link-building for external tools; no I/O, so it belongs in application, not outbound."""

from collections.abc import Mapping
from urllib.parse import quote, urlencode

from capataz_api.domain.entities import Connector, Service
from capataz_api.domain.specs import GrafanaConnector, LokiConnector, PortainerConnector


def _base(url: object) -> str:
    return str(url).rstrip("/")


def resolve_links(service: Service, connectors: Mapping[str, Connector]) -> dict[str, str]:
    """Deep links keyed by name; each dashboard is keyed by its label (default "grafana")."""
    spec = service.spec
    links: dict[str, str] = {}
    if spec.service_url:
        links["service"] = str(spec.service_url)
    if spec.documentation_url:
        links["documentation"] = str(spec.documentation_url)

    runtime = spec.runtime
    portainer = connectors.get(runtime.connector) if runtime else None
    if runtime and portainer and isinstance(portainer.spec, PortainerConnector):
        path = f"#!/{runtime.environment_id}/docker/{runtime.selector_kind}"
        links["portainer"] = f"{_base(portainer.spec.config.url)}/{path}"

    for dashboard in spec.observability.dashboards:
        grafana = connectors.get(dashboard.connector)
        if grafana is None or not isinstance(grafana.spec, GrafanaConnector):
            continue
        base = _base(grafana.spec.config.url)
        if dashboard.url:
            # An explicit url is the full, final path (or already-absolute URL): it wins over
            # uid/slug/variables entirely, since the caller has already resolved those.
            links[dashboard.label] = (
                dashboard.url
                if dashboard.url.startswith(("http://", "https://"))
                else f"{base}/{dashboard.url.lstrip('/')}"
            )
            continue
        # Variables pass through verbatim (not auto-prefixed with "var-") so a service can also
        # set non-variable query params Grafana recognizes, e.g. kiosk=tv.
        suffix = f"?{urlencode(dashboard.variables)}" if dashboard.variables else ""
        # safe="/" lets a legacy uid still carry a folder path without Grafana rejecting %2F.
        path = f"d/{quote(str(dashboard.uid), safe='/')}"
        if dashboard.slug:
            path = f"{path}/{dashboard.slug}"
        links[dashboard.label] = f"{base}/{path}{suffix}"

    logs = spec.observability.logs
    loki = connectors.get(logs.connector) if logs else None
    if logs and loki and isinstance(loki.spec, LokiConnector):
        links["loki"] = f"{_base(loki.spec.config.url)}/explore?{urlencode({'left': logs.query})}"
    return links
