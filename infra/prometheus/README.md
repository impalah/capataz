# Prometheus (reserved, not enabled in V1)

*Language: **English** · [Español](README.es.md)*

This directory exists per the monorepo's agreed structure, to host, in the future, example
configuration for Prometheus integration (scrape configs, rules, reference dashboards).

In V1, Capataz does **not** implement a `PrometheusPort` with credentials or PromQL queries on
service cards — see [docs/01-architecture.md](../../docs/01-architecture.en.md) and [docs/06-security.md](../../docs/06-security.en.md). Once the port/adapter is implemented in
a future phase, its example configuration (no credentials) should live here.
