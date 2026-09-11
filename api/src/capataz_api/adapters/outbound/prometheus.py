import asyncio
from typing import Any

import httpx
from loguru import logger


class PrometheusMetricsProvider:
    """Runs admin-authored PromQL (catalog `metrics[].query`) verbatim against Prometheus.

    The query text is never client input — only capataz-admin can write/edit the catalog (same
    trust level as HealthCatalog.url or an Ansible playbook path) — so it is passed through as-is,
    never templated or concatenated with anything else. See docs/06-security.md.
    """

    def __init__(
        self, base_url: str, token: str | None, timeout: float = 5, verify: bool = True
    ) -> None:
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.verify = verify

    async def query(self, definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=headers, verify=self.verify
        ) as client:
            values = await asyncio.gather(
                *(self._run_query(client, str(d["query"])) for d in definitions)
            )
        return [
            {"label": definition["label"], "value": value}
            for definition, value in zip(definitions, values, strict=True)
        ]

    async def _run_query(self, client: httpx.AsyncClient, query: str) -> float | None:
        try:
            response = await client.get(f"{self.base_url}/api/v1/query", params={"query": query})
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                logger.warning(f"Prometheus query returned status={payload.get('status')!r}")
                return None
            rows = payload["data"]["result"]
            if not rows:
                return None
            # If the admin's query wasn't already fully aggregated to one series, summing the
            # returned series is a reasonable fallback (mirrors the `sum by (...)` idiom already
            # used elsewhere in this homelab's own Grafana dashboards).
            return sum(float(row["value"][1]) for row in rows)
        except httpx.HTTPError as exc:
            logger.warning(f"Prometheus query failed: {exc}")
            return None
        except Exception:
            # Malformed/unexpected JSON shape (missing keys, wrong types, ...) is treated the same
            # as a network failure: metrics are informational, never worth breaking status refresh.
            logger.warning("Prometheus query returned an unexpected response shape")
            return None
