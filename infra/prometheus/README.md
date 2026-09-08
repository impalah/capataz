# Prometheus metrics adapter

*Language: **English** · [Español](README.es.md)*

Capataz's API queries this homelab's existing Prometheus to show per-service metrics (CPU,
memory, or anything else an operator declares) on the "Servicios" dashboard cards, via a
`MetricsProviderPort` / `PrometheusMetricsProvider`
(`api/src/capataz_api/adapters/outbound/prometheus.py`), selected by
`CAPATAZ_METRICS_PROVIDER=prometheus|none` and pointed at `CAPATAZ_PROMETHEUS_URL` — see
[docs/01-architecture.md](../../docs/01-architecture.en.md),
[docs/05-yaml-catalog.md](../../docs/05-yaml-catalog.en.md) and
[docs/06-security.md](../../docs/06-security.en.md).

## How it works

Each service's catalog entry declares its own list of metrics:

```yaml
metrics:
  - label: CPU
    type: prometheus
    query: 'avg(rate(container_cpu_usage_seconds_total{...}[30s])) * 100'
  - label: Memoria
    type: prometheus
    query: 'avg(container_memory_working_set_bytes{...}) / 1024 / 1024'
```

`query` is the complete PromQL text — there is no fixed/built-in query and no per-service
selector the adapter builds on the admin's behalf. It is run through Prometheus's
`/api/v1/query` verbatim (never templated or string-concatenated with anything else). This is
safe because `metrics[].query` is **catalog config, not client input**: only `capataz-admin` can
write or edit the catalog (same trust level as `health.url` or an Ansible playbook path) — see
the "Trust boundary" note in docs/05-yaml-catalog.md and docs/06-security.md.

Metrics are queried by `StatusService.refresh` alongside the existing Portainer/health checks and
returned in the same `refresh-status` response — there is no separate metrics endpoint or cache
(there is no status cache at all: `POST /services/{id}/refresh-status` always runs the real
Portainer/health/Prometheus checks). Each metric is queried independently: one bad/slow query
returns `value: null` for that metric without affecting the service's status, containers, health,
or its other metrics.

## Credentials

None by default. If this Prometheus ever needs authentication, the adapter already accepts an
optional bearer token read from the `prometheus_token` Docker secret
(`api/src/capataz_api/bootstrap/lifespan.py`) — mount that secret to enable it; no code change is
required.

## Scrape config

No Capataz-specific scrape config is required — this directory has no example configuration to
add, since every query is authored per-service in the catalog rather than assuming a fixed set of
labels here.
