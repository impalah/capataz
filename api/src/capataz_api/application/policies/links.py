"""Pure link-building for external tools; no I/O, so it belongs in application, not outbound."""

from urllib.parse import quote, urlencode


def resolve_links(
    service: object, portainer_url: str | None, grafana_url: str | None, loki_url: str | None
) -> dict[str, str]:
    links: dict[str, str] = {}
    for attr, key in (("service_url", "service"), ("documentation_url", "documentation")):
        if value := getattr(service, attr):
            links[key] = value
    if portainer_url and getattr(service, "portainer_environment_id", None):
        selectors = getattr(service, "container_selectors", {}) or {}
        kind = "services" if selectors.get("services") else "containers"
        path = f"#!/{service.portainer_environment_id}/docker/{kind}"
        links["portainer"] = f"{portainer_url.rstrip('/')}/{path}"
    grafana = getattr(service, "grafana_config", {}) or {}
    # grafana.base_url lets a service point at a different Grafana instance than the system
    # default (grafana_url) — some homelab services run their own, e.g. a per-node Grafana.
    base_url = str(grafana.get("base_url") or grafana_url or "").rstrip("/")
    if dashboard_url := grafana.get("dashboard_url"):
        # An explicit dashboard_url is the full, final path (or already-absolute URL): it wins
        # over dashboard_uid/variables entirely, since the caller has already resolved those.
        dashboard_url = str(dashboard_url)
        if dashboard_url.startswith(("http://", "https://")):
            links["grafana"] = dashboard_url
        elif base_url:
            links["grafana"] = f"{base_url}/{dashboard_url.lstrip('/')}"
    elif base_url and grafana.get("dashboard_uid"):
        # Variables are passed through verbatim (not auto-prefixed with "var-") so a service can
        # also set non-variable query params Grafana recognizes, e.g. kiosk=tv.
        variables = {
            str(key): str(value) for key, value in grafana.get("variables", {}).items()
        }
        suffix = f"?{urlencode(variables)}" if variables else ""
        # safe="/" lets dashboard_uid carry a folder path (e.g. "homelab-generic/generic-service")
        # without Grafana rejecting a %2F-encoded slash in that segment of the URL.
        dashboard_uid = quote(str(grafana["dashboard_uid"]), safe="/")
        links["grafana"] = f"{base_url}/d/{dashboard_uid}{suffix}"
    loki = getattr(service, "loki_config", {})
    if loki_url and loki.get("query"):
        links["loki"] = f"{loki_url.rstrip('/')}/explore?{urlencode({'left': loki['query']})}"
    return links
