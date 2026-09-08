# Adaptador de métricas Prometheus

*Idioma: **Español** · [English](README.md)*

El API de Capataz consulta el Prometheus ya existente en este homelab para mostrar métricas por
servicio (CPU, memoria o cualquier otra que declare el operador) en las tarjetas del dashboard
"Servicios", a través de un `MetricsProviderPort` / `PrometheusMetricsProvider`
(`api/src/capataz_api/adapters/outbound/prometheus.py`), seleccionado con
`CAPATAZ_METRICS_PROVIDER=prometheus|none` y apuntando a `CAPATAZ_PROMETHEUS_URL` — ver
[docs/01-architecture.md](../../docs/01-architecture.es.md),
[docs/05-yaml-catalog.md](../../docs/05-yaml-catalog.es.md) y
[docs/06-security.md](../../docs/06-security.es.md).

## Cómo funciona

Cada entrada del catálogo declara su propia lista de métricas:

```yaml
metrics:
  - label: CPU
    type: prometheus
    query: 'avg(rate(container_cpu_usage_seconds_total{...}[30s])) * 100'
  - label: Memoria
    type: prometheus
    query: 'avg(container_memory_working_set_bytes{...}) / 1024 / 1024'
```

`query` es el PromQL completo — no hay ninguna query fija/integrada ni ningún selector por
servicio que el adaptador construya por el admin. Se lanza tal cual contra `/api/v1/query` de
Prometheus (nunca plantillado ni concatenado con nada más). Esto es seguro porque
`metrics[].query` es **configuración del catálogo, no input de cliente**: solo `capataz-admin`
puede escribir o editar el catálogo (mismo nivel de confianza que `health.url` o un playbook de
Ansible) — ver la nota "Límite de confianza" en docs/05-yaml-catalog.md y docs/06-security.md.

Las métricas se consultan desde `StatusService.refresh` junto a las comprobaciones de
Portainer/health ya existentes, y se devuelven en la misma respuesta de `refresh-status` — no hay
endpoint ni caché de métricas propios (de hecho no hay ninguna caché de estado: `POST
/services/{id}/refresh-status` siempre ejecuta las comprobaciones reales de
Portainer/health/Prometheus). Cada métrica se consulta de forma independiente: una query lenta o
rota devuelve `value: null` para esa métrica sin afectar al estado, los contenedores, la salud del
servicio ni al resto de sus métricas.

## Credenciales

Ninguna por defecto. Si en algún momento este Prometheus necesitase autenticación, el adaptador
ya acepta un token bearer opcional leído del Docker secret `prometheus_token`
(`api/src/capataz_api/bootstrap/lifespan.py`) — basta con montar ese secreto para activarlo; no
hace falta tocar código.

## Configuración de scrape

No se necesita ninguna configuración de scrape específica de Capataz — este directorio no tiene
configuración de ejemplo que añadir, ya que cada query se escribe por servicio en el catálogo en
lugar de asumir aquí un conjunto fijo de etiquetas.
