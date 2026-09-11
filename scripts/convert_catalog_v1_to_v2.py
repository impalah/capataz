#!/usr/bin/env python3
"""Convert a Capataz v1 service catalog to the v2 format (resources/connectors/services).

v1 carried every integration inline on each service (portainer/health/grafana/loki/metrics) and
took the Portainer/Grafana/Loki/Prometheus URLs and credentials from global settings and Docker
secrets. v2 names those explicitly as connectors (typed connection plugins) and resources
(encrypted files/secrets). See docs/05-yaml-catalog.en.md.

The ids generated here (connectors `portainer`, `prometheus`, `grafana`, `loki`, `http`,
`ansible`; resources `portainer_token`, `runner_ssh_private_key`, ...) deliberately match the
placeholders migration 20260912_0009 creates, so importing the converted catalog replaces them in
place. Resources use `{file: <old Docker secret name>}` sources: mount those secrets under
CAPATAZ_RESOURCES_DIR with the same names.

Usage (PyYAML is the only dependency; the API's environment already has it):
    uv run --project api python scripts/convert_catalog_v1_to_v2.py catalog/v1.yaml -o out.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

DEFAULT_URLS = {
    "portainer": "https://portainer.404labo.net",
    # Scraped directly on its Swarm-published port: the public hostname sits behind an Authentik
    # forward-auth outpost that server-to-server calls can't pass.
    "prometheus": "http://prometheus.404labo.net:9090",
    "grafana": "https://grafana.404labo.net",
    "loki": "https://loki.404labo.net",
}

PORTAINER_TOKEN = "portainer_token"
SSH_KEY = "runner_ssh_private_key"
KNOWN_HOSTS = "runner_known_hosts"
VAULT_PASSWORD = "ansible_vault_password"

HEADER = """\
# Capataz service catalog, format v2 — see docs/05-yaml-catalog.en.md.
#
# resources:  files/secrets Capataz stores encrypted. `source: {file: X}` is read from
#             CAPATAZ_RESOURCES_DIR/X at import time; the content never lives in this file.
# connectors: typed connection plugins (portainer, prometheus, grafana, loki, http, ansible, ssh)
#             that reference resources for their credentials.
# services:   reference connectors for status (runtime), observability and actions.
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "custom"


class Converter:
    def __init__(self, urls: dict[str, str]) -> None:
        self.urls = urls
        self.resources: dict[str, dict[str, Any]] = {}
        self.connectors: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []

    def resource(self, resource_id: str, resource_type: str) -> str:
        self.resources.setdefault(
            resource_id,
            {"id": resource_id, "type": resource_type, "source": {"file": resource_id}},
        )
        return resource_id

    def connector(
        self, connector_id: str, connector_type: str, config: dict[str, Any]
    ) -> str:
        existing = self.connectors.get(connector_id)
        if existing is None:
            entry: dict[str, Any] = {"id": connector_id, "type": connector_type}
            if config:
                entry["config"] = config
            self.connectors[connector_id] = entry
        elif existing.get("config", {}) != config:
            raise ValueError(f"conflicting definitions for connector {connector_id!r}")
        return connector_id

    def portainer(self) -> str:
        token = self.resource(PORTAINER_TOKEN, "secret")
        return self.connector(
            "portainer", "portainer", {"url": self.urls["portainer"], "token": token}
        )

    def grafana(self, base_url: str | None) -> str:
        default = self.urls["grafana"]
        if not base_url or base_url.rstrip("/") == default.rstrip("/"):
            return self.connector("grafana", "grafana", {"url": default})
        host = urlparse(base_url).hostname or "custom"
        return self.connector(f"grafana_{_slug(host)}", "grafana", {"url": base_url})

    def ansible(self, inventory: str) -> str:
        stem = Path(inventory).stem
        connector_id = "ansible" if stem == "homelab" else f"ansible_{_slug(stem)}"
        return self.connector(
            connector_id,
            "ansible",
            {
                "inventory": inventory,
                "private_key": self.resource(SSH_KEY, "ssh_private_key"),
                "known_hosts": self.resource(KNOWN_HOSTS, "known_hosts"),
                "vault_password": self.resource(VAULT_PASSWORD, "secret"),
            },
        )

    def service(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            key: item[key]
            for key in (
                "id",
                "name",
                "description",
                "group_name",
                "environment",
                "icon",
                "service_url",
                "documentation_url",
            )
            if item.get(key) is not None
        }
        runtime = self._runtime(item.get("portainer"))
        if runtime:
            out["runtime"] = runtime
        observability = self._observability(item)
        if observability:
            out["observability"] = observability
        if item.get("metadata"):
            out["metadata"] = item["metadata"]
        if item.get("maintenance"):
            out["maintenance"] = True
        actions = [
            converted
            for action in item.get("actions") or []
            if (converted := self._action(item["id"], action, runtime)) is not None
        ]
        if actions:
            out["actions"] = actions
        return out

    def _runtime(self, portainer: dict[str, Any] | None) -> dict[str, Any] | None:
        if not portainer:
            return None
        kind = "services" if portainer.get("services") else "containers"
        runtime: dict[str, Any] = {
            "connector": self.portainer(),
            "environment_id": str(portainer["environment_id"]),
        }
        if portainer.get("stack_name"):
            runtime["stack_name"] = portainer["stack_name"]
        runtime["aggregation"] = portainer.get("aggregation", "all_required")
        runtime[kind] = portainer[kind]
        return runtime

    def _observability(self, item: dict[str, Any]) -> dict[str, Any]:
        observability: dict[str, Any] = {}
        health = item.get("health")
        if health:
            if health.get("type", "http") != "http":
                self.warnings.append(
                    f"{item['id']}: {health['type']} health checks are not supported; dropped"
                )
            else:
                check = {
                    "connector": self.connector("http", "http", {}),
                    "url": health["url"],
                }
                for key in ("expected_status", "timeout_seconds"):
                    if key in health:
                        check[key] = health[key]
                observability["health"] = check
        grafana = item.get("grafana") or {}
        if grafana.get("dashboard_uid") or grafana.get("dashboard_url"):
            dashboard: dict[str, Any] = {
                "label": "grafana",
                "connector": self.grafana(grafana.get("base_url")),
            }
            if grafana.get("dashboard_uid"):
                # v1 sometimes carried "uid/slug" in one string; v2 keeps them apart.
                uid, _, slug = str(grafana["dashboard_uid"]).partition("/")
                dashboard["uid"] = uid
                if slug:
                    dashboard["slug"] = slug
            if grafana.get("dashboard_url"):
                dashboard["url"] = grafana["dashboard_url"]
            if grafana.get("variables"):
                dashboard["variables"] = {
                    str(k): str(v) for k, v in grafana["variables"].items()
                }
            observability["dashboards"] = [dashboard]
        loki = item.get("loki") or {}
        if loki.get("query"):
            connector = self.connector("loki", "loki", {"url": self.urls["loki"]})
            observability["logs"] = {"connector": connector, "query": loki["query"]}
        metrics = item.get("metrics") or []
        if metrics:
            prometheus = self.connector(
                "prometheus", "prometheus", {"url": self.urls["prometheus"]}
            )
            observability["metrics"] = [
                {
                    "label": metric["label"],
                    "connector": prometheus,
                    "query": metric["query"],
                }
                for metric in metrics
            ]
        return observability

    def _action(
        self, service_id: str, action: dict[str, Any], runtime: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        action_type = action.get("action_type")
        config = dict(action.get("config") or {})
        if action_type == "portainer":
            if runtime is None:
                self.warnings.append(
                    f"{service_id}.{action['key']}: portainer action without portainer; dropped"
                )
                return None
            connector = runtime["connector"]
        elif action_type == "ansible":
            connector = self.ansible(
                str(config.pop("inventory", "inventories/homelab.yml"))
            )
        else:
            self.warnings.append(
                f"{service_id}.{action['key']}: {action_type} actions were never executable; "
                "dropped"
            )
            return None
        out: dict[str, Any] = {
            key: action[key]
            for key in ("key", "label", "description", "icon")
            if action.get(key)
        }
        out["risk_level"] = action["risk_level"]
        for flag, default in (
            ("requires_confirmation", False),
            ("enabled", True),
            ("unattended", False),
        ):
            if action.get(flag, default) != default:
                out[flag] = action[flag]
        out["connector"] = connector
        out["config"] = config
        if action.get("allowed_parameters_schema"):
            out["allowed_parameters_schema"] = action["allowed_parameters_schema"]
        return out


def convert(
    document: dict[str, Any], urls: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    converter = Converter(urls)
    services = [converter.service(item) for item in document.get("services") or []]
    return (
        {
            "version": 2,
            "resources": list(converter.resources.values()),
            "connectors": list(converter.connectors.values()),
            "services": services,
        },
        converter.warnings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path, help="v1 catalog YAML")
    parser.add_argument(
        "-o", "--output", type=Path, help="write here instead of stdout"
    )
    for name, url in DEFAULT_URLS.items():
        parser.add_argument(
            f"--{name}-url", default=url, help=f"{name} connector URL ({url})"
        )
    args = parser.parse_args(argv)

    document = yaml.safe_load(args.input.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        print(f"{args.input}: not a version 1 catalog", file=sys.stderr)
        return 2
    urls = {name: getattr(args, f"{name}_url") for name in DEFAULT_URLS}
    converted, warnings = convert(document, urls)
    text = HEADER + yaml.safe_dump(
        converted, allow_unicode=True, sort_keys=False, width=1_000_000
    )
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
