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
        path = f"#!/{service.portainer_environment_id}/docker/containers"
        links["portainer"] = f"{portainer_url.rstrip('/')}/{path}"
    grafana = getattr(service, "grafana_config", {})
    if grafana_url and grafana.get("dashboard_uid"):
        variables = {
            f"var-{key}": str(value) for key, value in grafana.get("variables", {}).items()
        }
        suffix = f"?{urlencode(variables)}" if variables else ""
        dashboard_uid = quote(str(grafana["dashboard_uid"]), safe="")
        links["grafana"] = f"{grafana_url.rstrip('/')}/d/{dashboard_uid}{suffix}"
    loki = getattr(service, "loki_config", {})
    if loki_url and loki.get("query"):
        links["loki"] = f"{loki_url.rstrip('/')}/explore?{urlencode({'left': loki['query']})}"
    return links
