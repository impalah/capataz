# Prometheus metrics adapter

*Language: **English** · [Español](README.es.md)*

Capataz's API queries this homelab's existing Prometheus to show per-service metrics (CPU,
memory, or anything else an operator declares) on the "Servicios" dashboard cards, via a
`MetricsProviderPort` / `PrometheusMetricsProvider`
(`api/src/capataz_api/adapters/outbound/prometheus.py`), built per `prometheus` **connector** of
the catalog (its `url`, optional `token` resource and `verify_tls`) — see
[ADR 008](../../docs/adr/008-connectors-and-resources.en.md),
[docs/01-architecture.md](../../docs/01-architecture.en.md),
[docs/05-yaml-catalog.md](../../docs/05-yaml-catalog.en.md) and
[docs/06-security.md](../../docs/06-security.en.md).

## How it works

Each service's catalog entry declares its own list of metrics, each against a connector with the
`metrics` capability:

```yaml
connectors:
  - id: prometheus
    type: prometheus
    config: { url: http://prometheus.404labo.net:9090 }
services:
  - id: ollama
    # ...
    observability:
      metrics:
        - label: CPU
          connector: prometheus
          query: 'avg(rate(container_cpu_usage_seconds_total{...}[30s])) * 100'
        - label: Memoria
          connector: prometheus
          query: 'avg(container_memory_working_set_bytes{...}) / 1024 / 1024'
```

If the Prometheus hostname sits behind a forward-auth proxy (e.g. an Authentik outpost), point the
connector at an address that bypasses it — the proxy would answer the API with a 302 to its login
page. The homelab uses the direct `http://prometheus.404labo.net:9090`.

`query` is the complete PromQL text — there is no fixed/built-in query and no per-service
selector the adapter builds on the admin's behalf. It is run through Prometheus's
`/api/v1/query` verbatim (never templated or string-concatenated with anything else). This is
safe because `metrics[].query` is **catalog config, not client input**: only `capataz-admin` can
write or edit the catalog (same trust level as `health.url` or an Ansible playbook path) — see
the "Trust boundary" note in docs/05-yaml-catalog.md and docs/06-security.md.

Metrics are queried by `StatusService.refresh` alongside the existing Portainer/health checks and
returned in the same `refresh-status` response — there is no separate metrics endpoint or cache
(there is no status cache at all: `POST /services/{id}/refresh-status` always runs the real
Portainer/health/Prometheus checks). Metrics are grouped per connector and each is queried
independently: a bad/slow query — or an unreachable connector — returns `value: null` for the
affected metrics without affecting the service's status, containers, health, or its other metrics.

## Credentials

None by default. If a Prometheus needs authentication, set its connector's optional `token` to a
`secret` resource: it's sent as `Authorization: Bearer`. The resource is encrypted in the database
and decrypted by the API only when querying — no Docker secret or code change is required.

## Scrape config

No Capataz-specific scrape config is required — this directory has no example configuration to
add, since every query is authored per-service in the catalog rather than assuming a fixed set of
labels here.
