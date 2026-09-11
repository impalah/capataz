# Adaptador de métricas Prometheus

*Idioma: **Español** · [English](README.md)*

El API de Capataz consulta el Prometheus ya existente en este homelab para mostrar métricas por
servicio (CPU, memoria o cualquier otra que declare el operador) en las tarjetas del dashboard
"Servicios", a través de un `MetricsProviderPort` / `PrometheusMetricsProvider`
(`api/src/capataz_api/adapters/outbound/prometheus.py`), construido por cada **conector**
`prometheus` del catálogo (su `url`, su recurso `token` opcional y `verify_tls`) — ver
[ADR 008](../../docs/adr/008-connectors-and-resources.es.md),
[docs/01-architecture.md](../../docs/01-architecture.es.md),
[docs/05-yaml-catalog.md](../../docs/05-yaml-catalog.es.md) y
[docs/06-security.md](../../docs/06-security.es.md).

## Cómo funciona

Cada entrada del catálogo declara su propia lista de métricas, cada una contra un conector con la
capacidad `metrics`:

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

Si el hostname de Prometheus está detrás de un proxy de forward-auth (p. ej. un outpost de
Authentik), apunta el conector a una dirección que se lo salte — el proxy respondería a la API con
un 302 a su página de login. El homelab usa la directa `http://prometheus.404labo.net:9090`.

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
Portainer/health/Prometheus). Las métricas se agrupan por conector y cada una se consulta de forma
independiente: una query lenta o rota — o un conector inalcanzable — devuelve `value: null` para
las métricas afectadas sin afectar al estado, los contenedores, la salud del servicio ni al resto
de sus métricas.

## Credenciales

Ninguna por defecto. Si un Prometheus necesita autenticación, asigna al `token` opcional de su
conector un recurso `secret`: se envía como `Authorization: Bearer`. El recurso está cifrado en la
base de datos y la API solo lo descifra al consultar — no hace falta ningún Docker secret ni tocar
código.

## Configuración de scrape

No se necesita ninguna configuración de scrape específica de Capataz — este directorio no tiene
configuración de ejemplo que añadir, ya que cada query se escribe por servicio en el catálogo en
lugar de asumir aquí un conjunto fijo de etiquetas.
