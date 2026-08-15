# Prometheus (reservado, V1 no lo activa)

*Idioma: **Español** · [English](README.md)*

Este directorio existe según la estructura acordada del monorepo para alojar, en el futuro, ejemplos de
configuración de integración con Prometheus (scrape configs, reglas, dashboards de referencia).

En V1, Capataz **no** implementa un `PrometheusPort` con credenciales ni consultas PromQL en las tarjetas
de servicio — ver [docs/01-architecture.md](../../docs/01-architecture.es.md) y [docs/06-security.md](../../docs/06-security.es.md). Cuando se implemente el puerto/adapter en
una fase futura, su configuración de ejemplo (no credenciales) debería vivir aquí.
