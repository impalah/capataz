# Catálogo YAML

*Idioma: **Español** · [English](05-yaml-catalog.en.md)*

El catálogo es una forma declarativa, versionable y libre de secretos de definir servicios y acciones. La raíz contiene `version: 1` (único valor aceptado) y `services` (lista). El identificador `id` de cada servicio es un slug lógico inmutable (`^[a-z0-9][a-z0-9-]*$`) que sirve de clave de upsert en cada importación — no lo renombres para representar otro servicio; si necesitas sustituir un servicio, borra el antiguo y crea uno con `id` nuevo.

Este documento describe **cada campo tal y como está implementado hoy**, con su validación real y, cuando aplica, de dónde se obtiene el valor. El esquema de referencia vive en `api/src/capataz_api/application/dto/catalog.py` (`Catalog`/`ServiceCatalog`/`ActionCatalog`); si algo aquí y el código divergen, el código manda.

## Campos de servicio

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | string, slug | Sí | Identificador lógico e inmutable, clave de upsert. |
| `name` | string | Sí | Nombre mostrado en la tarjeta y en las cabeceras de detalle. |
| `description` | string | No | Texto bajo el nombre en la tarjeta de servicio. Se muestra a **una sola línea** con elipsis CSS (`.service-card p` en `frontend/src/styles/app.scss`) — una descripción larga se corta visualmente, así que conviene mantenerla breve (una frase). |
| `group_name` | string libre | Sí | Etiqueta de agrupación. No hay una entidad `Group` ni un allow-list: es un `str` suelto en `Service` (`domain/entities/models.py`). El desplegable "Grupo" del Dashboard (`DashboardPage.vue`) se rellena con los valores distintos que existan entre los servicios ya cargados — dos servicios deben escribir el nombre de grupo *exactamente* igual (mayúsculas/acentos incluidos) para agruparse juntos. |
| `environment` | string libre | Sí | Igual que `group_name` pero para el filtro "Entorno": string libre sin allow-list, usado solo para agrupar visualmente (en el catálogo de ejemplo se usa `homelab` para todos). |
| `icon` | string | No | Nombre de ligadura de [Material Icons](https://fonts.google.com/icons?icon.set=Material+Icons), la fuente que empaqueta Quasar (`@quasar/extras/material-icons`). **Debe existir literalmente en esa fuente** — un nombre inválido o de un set distinto (Material Symbols, Icons Outlined/Round, etc.) no lanza ningún error de validación: el catálogo lo acepta tal cual, pero en el navegador la ligadura no sustituye al texto y el `<i>` renderiza el string en bruto, desbordando la caja de 28px del icono (visible como `scrollWidth` > `offsetWidth` al inspeccionar el elemento) y "escapando" visualmente de la tarjeta. Antes de usar un nombre nuevo, ábrelo en la propia página de Google y confirma que pertenece al set **"Material Icons"** (el filled clásico), no a Symbols/Outlined/Round. |
| `service_url` | URL http/https | No | Enlace "Abrir servicio". Se expone tal cual al frontend (`resolve_links` en `application/policies/links.py`) — la API nunca hace una petición HTTP a esta URL, así que no pasa por la defensa SSRF (esa solo aplica a `health.url`, ver más abajo). |
| `documentation_url` | URL http/https | No | Enlace "Documentación". Mismo tratamiento que `service_url`: solo se muestra, nunca se llama desde el servidor. |
| `maintenance` | boolean, por defecto `false` | No | Si es `true`, el estado agregado del servicio se fuerza siempre a `maintenance` (ver `aggregate_status` en `application/policies/status.py`), sin consultar Portainer ni el healthcheck. **No está expuesto en el formulario de "Nuevo servicio"/"Editar servicio" de `CatalogPage.vue`** — solo se puede fijar importando YAML o llamando a la API en crudo (`PATCH /services/{id}`). |
| `metadata` | objeto libre | No | Bolsa de datos arbitraria, persistida y expuesta tal cual por la API (`GET /services/{id}`), pero **no leída por ninguna lógica de la aplicación ni mostrada en el frontend** hoy. Útil como anotación propia o para integraciones futuras, sin efecto funcional actual. |

## `portainer`

Un servicio declara **exactamente uno** de `containers` o `services` (nunca ambos, nunca ninguno — lo impone el propio validador de `PortainerCatalog`) según cómo esté desplegado:

- `containers` — un despliegue standalone/Compose donde el contenedor mantiene un nombre fijo y predecible (p. ej. `docker run --name ollama` o un `container_name:` de Compose). Se empareja contra el listado de contenedores de Portainer por nombre exacto.
- `services` — un service de Docker Swarm (`docker stack deploy`). Swarm no permite fijar el nombre de un contenedor y lo genera por tarea/réplica (`{stack}_{service}.{slot}.{task-id}`), así que el emparejamiento por nombre exacto nunca funciona para un servicio desplegado en Swarm — `services` empareja en su lugar contra el nombre de **service** de Swarm, estable y propio de Docker (`{stack_name}_{name}`), usando la API de Services de Docker Engine en vez del listado de contenedores.

```yaml
# Contenedor standalone / docker-compose
portainer:
  environment_id: 5
  stack_name: homelab-ryzen
  aggregation: all_required
  containers:
    - name: ollama
      required: true
      critical: false
```

```yaml
# Servicio de Docker Swarm
portainer:
  environment_id: 7
  stack_name: homelab-swarm
  aggregation: all_required
  services:
    - name: authentik-server
      replicas: 1
      required: true
      critical: false
```

| Campo | Descripción |
|---|---|
| `environment_id` | El **endpoint ID** de Portainer (no es libre): es el número que Portainer asigna a cada entorno registrado. Se obtiene en la UI de Portainer (**Environments**, columna del entorno) o consultando `GET {portainer_url}/api/endpoints` con el token de servicio (cabecera `X-API-Key`) — así es como se resolvió `environment_id` para cada nodo del clúster al dar de alta los 25 servicios nuevos del catálogo. El runner lo usa literalmente en la ruta `api/endpoints/{environment_id}/docker/containers/...` o `.../docker/services/...` (`runner/src/capataz_runner/executor.py`), así que un valor incorrecto no falla la validación del YAML, falla en tiempo de ejecución contra Portainer. |
| `stack_name` | Con `containers`, es **puramente informativo** — se persiste y se muestra en la tarjeta ("Stack: homelab-retaco"), pero no se usa para resolver ni filtrar contenedores (solo `containers[].name` se usa para eso). Con `services`, **sí se usa**: cada nombre de servicio declarado se resuelve como `{stack_name}_{name}` contra el listado de services de Swarm, exactamente igual que nombra las cosas `docker stack deploy -c file.yml {stack_name}` — un `stack_name` incorrecto aquí significa que ningún servicio va a emparejar nunca. |
| `aggregation` | `all_required` (por defecto) o `any_healthy`. Determina cómo se combinan los contenedores/servicios observados para el estado agregado (`aggregate_status` en `application/policies/status.py`): con `all_required`, el servicio es `healthy` solo si **todos** los elementos con `required: true` están corriendo (y sanos — para un servicio Swarm, "sano" significa que su número de tareas corriendo coincide con el deseado); con `any_healthy`, basta con que **alguno** esté corriendo y sano. En ambos casos, si el healthcheck externo (`health:`) declarado falla, el servicio baja a `degraded`/`down` según el caso. |
| `containers[].name` | Nombre **exacto** del contenedor en Docker (`docker ps --format '{{.Names}}'` en el nodo, o el nombre visible en Portainer). Es el único dato que el runner y el `StatusService` usan para localizar el contenedor dentro del `environment_id` declarado — no se acepta un ID de contenedor suministrado por el cliente en ningún punto del flujo. |
| `containers[].required` / `containers[].critical` | Por defecto `true`/`false`. `required: false` significa que el contenedor se observa e informa pero no cuenta para `down` bajo `aggregation: all_required`. `critical: true` marca el servicio `down` incondicionalmente cuando ese contenedor concreto no está corriendo, sin importar `aggregation` ni el estado de los demás. |
| `services[].name` | El nombre corto del service de Swarm, **sin** el prefijo del stack (p. ej. `authentik-server`, no `homelab-swarm_authentik-server`) — el nombre completo se deriva de `stack_name` + este campo. |
| `services[].replicas` | 0–50, por defecto `1`. El número de réplicas al que una acción `start` reescala el servicio, y contra el que se compara `RunningTasks` para decidir si está sano/completamente escalado. Si el servicio se reescala alguna vez fuera de Capataz (`docker service scale`), el siguiente `start`/`restart` desde Capataz lo volverá a dejar en este valor declarado — hay que mantenerlo sincronizado con la capacidad deseada real. |
| `services[].required` / `services[].critical` | Misma semántica que sus equivalentes en `containers[]`. |

## `health`

```yaml
health:
  type: http
  url: https://openwebui.404labo.net/health
  expected_status: 200
  timeout_seconds: 5
```

| Campo | Descripción |
|---|---|
| `type` | `http` o `tcp` en el esquema (`Literal["http", "tcp"]`), pero **solo `http` está implementado**: `HttpHealthProber` (`adapters/outbound/health.py`) siempre hace una petición HTTP GET, cualquiera que sea el valor de `type`. Declarar `type: tcp` no lanza un error de validación ni hace un connect TCP real — hoy se comporta exactamente igual que `http`. No lo uses hasta que este ítem se implemente. |
| `url` | Debe ser `http`/`https` con hostname. Sujeta a defensa SSRF real (`validate_health_url`): se rechaza si el host es una IP (salvo que además termine en un sufijo permitido), si resuelve a loopback/link-local/rango privado, o si el hostname no termina en uno de los sufijos de `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (por defecto `.404labo.net`; ver `core/settings.py`). Esta es la **única** URL del catálogo que la API llega a solicitar por sí misma; `service_url`/`documentation_url` no pasan por aquí porque nunca se piden desde el servidor. |
| `expected_status` | Código HTTP considerado "sano" (100–599, por defecto `200`). |
| `timeout_seconds` | 1–60, por defecto `5`. |

## `grafana` / `loki`

Ambos son objetos **completamente libres** (`dict[str, Any]`, sin validación de forma ni de claves permitidas pese a lo que sugiera el nombre) que `resolve_links` (`application/policies/links.py`) usa para construir enlaces de solo-lectura hacia herramientas externas — no se llama al servidor de Grafana/Loki desde la API, así que tampoco pasan por la defensa SSRF.

```yaml
grafana:
  dashboard_uid: homelab-generico/servicio-generico
  variables:
    var-service: ollama-service
    kiosk: tv
loki:
  query: '{compose_service="ollama"}'
```

- `grafana.dashboard_uid`: UID del panel en tu Grafana (visible en la URL del dashboard: `.../d/<uid>/...`). Se concatena literalmente en `{grafana.base_url o grafana_url}/d/{dashboard_uid}`; el carácter `/` no se codifica, así que un UID cualificado por carpeta como `homelab-generico/servicio-generico` funciona tal cual.
- `grafana.variables`: pares clave/valor que se usan tal cual como parámetros de la URL — no se añade ningún prefijo automáticamente, así que hay que indicar el nombre **completo** del parámetro que espera Grafana, p. ej. `var-service` para una variable de plantilla llamada `service`, o un modificador que no sea variable, como `kiosk: tv`. Un parámetro que no coincida con ninguna variable de plantilla definida en ese dashboard, Grafana simplemente lo ignora.
- `grafana.base_url`: opcional; sobrescribe la `CAPATAZ_GRAFANA_URL` del sistema solo para este servicio, para un servicio cuyos dashboards viven en otra instancia de Grafana.
- `grafana.dashboard_url`: opcional; la ruta completa del dashboard (o una URL `http(s)://` completa) a usar como enlace de Grafana, **ignorando por completo `dashboard_uid` y `variables`** si está definida. Un valor relativo (que no empiece por `http://`/`https://`) se añade a `grafana.base_url` o a la `CAPATAZ_GRAFANA_URL` del sistema.
- `loki.query`: expresión LogQL en bruto que se coloca como parámetro `left` de `{loki_url}/explore?...`. Sin escapado más allá del `urlencode` estándar.

`CAPATAZ_GRAFANA_URL`/`CAPATAZ_LOKI_URL`/`CAPATAZ_PORTAINER_URL` (variables de entorno, ver `core/settings.py`) deben estar configuradas para que estos enlaces se generen, salvo que `grafana.base_url` (o un `grafana.dashboard_url` absoluto) aporte la suya propia; si ninguna de estas fuentes da una URL base, el enlace simplemente no aparece.

## `metrics`

```yaml
metrics:
  - label: CPU
    type: prometheus
    query: 'avg(rate(container_cpu_usage_seconds_total{container_label_com_docker_stack_namespace="ollama-service"}[30s])) * 100'
  - label: Memoria
    type: prometheus
    query: 'avg(container_memory_working_set_bytes{container_label_com_docker_stack_namespace="ollama-service"}) / 1024 / 1024'
```

Lista opcional de métricas a mostrar en la tarjeta y en el detalle de este servicio. Cada entrada:

| Campo | Descripción |
|---|---|
| `label` | Texto libre que se muestra encima del valor en la tarjeta (1–100 caracteres). No se localiza — es lo que escriba el admin. |
| `type` | `Literal["prometheus"]` hoy — el único proveedor implementado. El esquema (`MetricDefinitionCatalog`) y el `MetricsProviderPort` al que mapea son agnósticos del proveedor, así que un adaptador futuro (Netdata, CloudWatch, ...) solo añade otro valor literal aquí, sin cambiar la forma de este campo. |
| `query` | El texto **completo** de PromQL (1–2000 caracteres), ejecutado tal cual contra `{CAPATAZ_PROMETHEUS_URL}/api/v1/query`. Si Prometheus devuelve más de una serie (la query no quedó del todo agregada a un único valor), las series se suman. |

**Límite de confianza:** a diferencia del hostname validado por SSRF de `health.url` o de los `extra_vars` de Ansible con allow-list en el runner, `query` no tiene validación de forma/contenido más allá de un límite de longitud — se confía en él tal cual. Esto es intencionado y seguro: `metrics` lo escribe quien puede editar el catálogo (solo `capataz-admin`, con el mismo RBAC que protege cualquier otra mutación del catálogo), nunca se deriva de una petición de ejecución ni de ningún otro input de usuario final en tiempo de petición. Trata una `query` del catálogo igual que tratarías una `health.url` o la ruta de un playbook de Ansible — configuración de operador, no algo a aceptar de una fuente no confiable. Ver docs/06-security.md.

Las métricas las consulta `StatusService` del API junto a las comprobaciones de Portainer/health ya existentes — ver [infra/prometheus/README.es.md](../infra/prometheus/README.es.md) para cómo funciona la consulta y el cacheo. Un servicio sin bloque `metrics` simplemente no muestra fila de métricas.

## `actions`

```yaml
actions:
  - key: restart
    label: Reiniciar
    description: Reinicia el contenedor sin perder datos persistidos.
    icon: restart_alt
    action_type: portainer
    risk_level: operate
    requires_confirmation: true
    enabled: true
    unattended: true
    config:
      operation: restart
      target: selected_containers
    allowed_parameters_schema: {}
```

| Campo | Descripción |
|---|---|
| `key` | Slug único **por servicio** (`^[a-z0-9][a-z0-9-]*$`), identifica la acción en la URL de ejecución y en el upsert. |
| `label` | Texto/tooltip del botón en la tarjeta y en las páginas de servicio/ejecución. |
| `description` | Se persiste y se expone por API, pero **no se muestra en ningún punto del frontend actual** (ni tooltip, ni detalle) — documenta la acción solo de cara a quien lea/exporte el YAML. |
| `icon` | Igual que el `icon` de servicio: ligadura de Material Icons; mismo riesgo si el nombre no existe en la fuente empaquetada. |
| `action_type` | `portainer`, `ansible`, `http`, `ssh` o `rsync`. El esquema acepta los cinco, pero **solo `portainer` y `ansible` ejecutan de verdad**: `resolve_action` (`application/policies/actions.py`) rechaza explícitamente `http`/`ssh`/`rsync` en tiempo de ejecución con `"Action type is modelled but not executable in V1"` — se pueden declarar y ver en el catálogo, pero cualquier intento de ejecutarlas falla siempre. Ver `docs/12-roadmap.md` (ítem "Connectors") para la propuesta de darles conexión real. |
| `risk_level` | `read`, `operate` o `critical`. Ver tabla de roles más abajo — **no es solo informativo**, determina qué rol mínimo puede ejecutar la acción. |
| `requires_confirmation` | Booleano, por defecto `false`. **Declarado pero no implementado.** Se puede fijar desde YAML o desde el formulario "Nueva acción" de `CatalogPage.vue`, se persiste, y se devuelve por API — pero ningún punto del flujo de ejecución lo lee: ni `authorize_action` (`application/policies/rbac.py`, que solo mira `risk_level`), ni el frontend (`ServiceCard.vue`/`ServiceDetailPage.vue` deciden si mostrar el diálogo de confirmación mirando literalmente `action.risk_level === 'critical'`, no este campo). Hoy, marcar `requires_confirmation: true` en una acción `operate` no tiene ningún efecto observable. Lo que debería hacer: exigir confirmación explícita (y opcionalmente un motivo) al ejecutar, de forma independiente de `risk_level`, para poder marcar como "requiere confirmación" una acción `operate` sin tener que subirla a `critical` (p. ej. un `restart` que afecta a otros servicios). |
| `enabled` | Booleano, por defecto `true`. Si es `false`, `resolve_action` rechaza cualquier intento de ejecución (`"Action is not enabled for this service"`) — este sí está implementado y activo. |
| `unattended` | Booleano, por defecto `false`. Preferencia de UI, no de seguridad: si es `true`, el frontend lanza la acción y permanece en la pantalla de origen refrescando el estado del servicio, en vez de navegar al detalle de la ejecución. Pensado para acciones rápidas de un solo paso (`start`/`stop`/`restart`); déjalo en `false` para acciones cuya salida interesa inspeccionar (`logs`, acciones Ansible). |
| `config` | Validada según `action_type`, ver abajo. Nunca puede contener la clave `command` (rechazado siempre, cualquiera que sea el tipo). |
| `allowed_parameters_schema` | Objeto tipo JSON-Schema simplificado: `{"properties": {"<param>": {"enum": [...]}}}`. Si se define, **sí se aplica** en `resolve_action`: cualquier parámetro enviado en la ejecución (`POST .../execute`, campo `params`) que no esté en `properties` se rechaza, y si la definición de un parámetro trae `enum`, el valor enviado debe estar en esa lista. Las claves `command`, `container_id`, `url` y `playbook_path` están además prohibidas como parámetro de ejecución siempre, sin importar este esquema. Si se omite (`{}`, el valor por defecto), la acción no acepta ningún parámetro en la ejecución. |

### `config` para `action_type: portainer`

Solo se acepta exactamente esta forma — cualquier otra clave, o un valor fuera de estas listas, se rechaza tanto en la validación del catálogo como (por duplicado, como cinturón y tirantes) en el runner:

```yaml
config:
  operation: restart              # start | stop | restart | logs
  target: selected_containers     # selected_containers | selected_services
```

`target` debe ser `selected_containers` o `selected_services`, y **debe coincidir con el tipo de selector declarado en el propio bloque `portainer` del servicio** (`selected_services` cuando declara `services`, `selected_containers` cuando declara `containers` — un desajuste se rechaza en tiempo de validación del catálogo, en el propio validador de `ServiceCatalog`). Nunca se acepta un ID de contenedor/servicio específico desde el cliente/catálogo — el runner resuelve el destino real a partir de `service.container_selectors` (el bloque `portainer.containers`/`portainer.services`), nunca desde `config`.

Para `selected_services`, las cuatro operaciones se traducen a la API de Services de Docker Swarm en vez de a los verbos start/stop/restart/logs de contenedor (un service de Swarm no los tiene): `restart` es un **force update** (equivalente a `docker service update --force` — redespliega todas las tareas con el mismo spec/imagen), `logs` agrega los logs de todas las tareas del servicio, y `stop`/`start` **escalan réplicas a 0 / de vuelta al `services[].replicas` declarado** — no eliminan ni recrean el servicio. Como `start` siempre reafirma el valor declarado en `replicas`, un servicio reescalado fuera de Capataz volverá a ese valor en el siguiente `start`/`restart` lanzado desde Capataz.

### `config` para `action_type: ansible`

```yaml
config:
  playbook: playbooks/backup_service.yml
  inventory: inventories/homelab.yml
  limit: node-ai-01
  extra_vars:
    service: open-webui
  timeout_seconds: 600
```

Todo el bloque está sujeto a un allow-list fijo en el **runner** (`runner/src/capataz_runner/actions.py`), no en el catálogo YAML — el catálogo solo comprueba el prefijo de ruta (`playbooks/`/`inventories/`, sin `..`); la lista real y cerrada de valores aceptados es:

| Campo | Allow-list actual | Notas |
|---|---|---|
| `playbook` | `playbooks/restart_service.yml`, `playbooks/backup_service.yml`, `playbooks/check_connectivity.yml` (`ALLOWED_PLAYBOOKS`) | Debe ser exactamente uno de estos tres — no cualquier ruta bajo `playbooks/`. Añadir un playbook nuevo requiere añadirlo a `runner/playbooks/` **y** a esta constante en el código. |
| `inventory` | `inventories/homelab.yml`, `inventories/local.yml` (`ALLOWED_INVENTORIES`) | Igual, valor cerrado. |
| `limit` | Cualquier slug seguro (`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$`) que además exista como host/grupo en el inventario elegido. `inventories/homelab.yml` define hoy solo `node-ai-01` y `node-gpu-01` como placeholders — no los nodos reales del clúster (`retaco`, `ryzen`, `pi-*`) que sí están dados de alta en `catalog/services.example.yaml` vía Portainer. Los servicios cuyas acciones son de tipo `portainer` no se ven afectados; los que en el futuro necesiten una acción Ansible sí necesitarán primero añadir su host real a este inventario. |
| `extra_vars` | Solo las claves `service`, `backup_label` (`ALLOWED_EXTRA_VARS`); cada valor debe cumplir el mismo slug seguro que `limit`. | Cualquier otra clave se rechaza. |
| `timeout_seconds` | Entero entre 1 y 900 (por defecto 300 si se omite). | |

## Tabla de roles por `risk_level`

`risk_level` no es descriptivo: es lo que la API usa en `authorize_action` (`application/policies/rbac.py`) para decidir si el usuario autenticado puede ejecutar esa acción concreta.

| `risk_level` | Rol mínimo para **ejecutar** | Requisito adicional |
|---|---|---|
| `read` | `capataz-operator` | Ninguno. **Ojo:** que una acción sea de solo lectura (p. ej. `logs`) no la abre a `capataz-viewer` — cualquier ejecución, incluidas las de riesgo `read`, exige como mínimo rol operador. Un viewer solo puede *ver* servicios, estado, ejecuciones y auditoría ya existentes, nunca disparar una acción. |
| `operate` | `capataz-operator` | Ninguno. |
| `critical` | `capataz-admin` | La petición de ejecución debe incluir `confirmation: true` y un `reason` no vacío, o la API la rechaza (403) — esta es la única confirmación real que existe hoy en el sistema, y es incondicional para `critical` (no depende de `requires_confirmation`, ver arriba). |

## Ejemplo completo

`catalog/services.example.yaml` contiene el catálogo real del homelab (27 servicios a fecha de este documento) y sirve de referencia viva — más fiable que cualquier fragmento aislado de esta página, porque se valida e importa contra la API real.

## Prohibiciones

No incluyas contraseñas, tokens, claves, valores de Vault, DSN, comandos libres, `shell`, un playbook no versionado, un inventario externo, un ID de contenedor de cliente ni URL de ejecución. Esto será rechazado por la validación; que el YAML sea sintácticamente correcto no lo hace permitido.

## Importación, dry-run y exportación

- Arranque opcional: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. Si se configura pero no existe o no valida, el startup/readiness falla de forma explícita. Si valida, el upsert es transaccional e idempotente.
- API: `POST /api/v1/catalog/import` recibe `{"yaml":"...","dry_run":true}` para validar sin escribir y `dry_run=false` para persistir. La interfaz debe mostrar errores de línea/campo.
- CLI operativa: `make seed-catalog` importa el ejemplo mediante la CLI de API.
- Exportación: `GET /api/v1/catalog/export` o `make export-catalog > catalog/export.yaml`. El resultado elimina secretos, resultados transitorios y datos de ejecución.

Un import actualiza el servicio cuyo `id` coincide y sus acciones por identificador lógico; no borra implícitamente datos no presentes salvo una opción explícita y auditada que pueda añadirse en el futuro (ver `docs/12-roadmap.md`, ítem sobre `upsert_catalog`).

## Errores frecuentes

- **ID duplicado / key duplicada**: usa un `id` único global y una `key` única por servicio.
- **URL de `health` rechazada**: el host/scheme no pasa la política SSRF o no está en el sufijo allow-listado (`CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES`). `service_url`/`documentation_url` nunca se rechazan por este motivo porque no se solicitan desde el servidor.
- **Acción `ansible` inválida**: playbook/inventario fuera de las constantes `ALLOWED_PLAYBOOKS`/`ALLOWED_INVENTORIES` del runner (no de un allow-list en el YAML), `limit` con caracteres no permitidos, `extra_vars` con una clave fuera de `ALLOWED_EXTRA_VARS`, o `timeout_seconds` fuera de 1–900.
- **Acción `http`/`ssh`/`rsync`**: se guarda sin error, pero cualquier ejecución fallará siempre con `"Action type is modelled but not executable in V1"` — no es un catálogo mal escrito, es una limitación conocida (ver `docs/12-roadmap.md`).
- **Icono que no se ve o se sale de la tarjeta**: el nombre no existe en la fuente Material Icons empaquetada — confírmalo en [fonts.google.com/icons](https://fonts.google.com/icons?icon.set=Material+Icons) dentro del set **"Material Icons"** (no Symbols/Outlined/Round).
- **Catálogo de arranque ausente**: corrige la ruta montada; no desactives el fallo sin entender por qué.
