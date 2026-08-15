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

```yaml
portainer:
  environment_id: 5
  stack_name: homelab-ryzen
  aggregation: all_required
  containers:
    - name: ollama
      required: true
      critical: false
```

| Campo | Descripción |
|---|---|
| `environment_id` | El **endpoint ID** de Portainer (no es libre): es el número que Portainer asigna a cada entorno registrado. Se obtiene en la UI de Portainer (**Environments**, columna del entorno) o consultando `GET {portainer_url}/api/endpoints` con el token de servicio (cabecera `X-API-Key`) — así es como se resolvió `environment_id` para cada nodo del clúster al dar de alta los 25 servicios nuevos del catálogo. El runner lo usa literalmente en la ruta `api/endpoints/{environment_id}/docker/containers/...` (`runner/src/capataz_runner/executor.py`), así que un valor incorrecto no falla la validación del YAML, falla en tiempo de ejecución contra Portainer. |
| `stack_name` | **Puramente informativo.** Se persiste y se muestra en la tarjeta ("Stack: homelab-retaco") pero no se usa para resolver ni filtrar contenedores — el emparejamiento real de contenedores usa solo `containers[].name` (ver abajo). Conviene que coincida con la etiqueta real `com.docker.compose.project` del stack en Docker para que la información mostrada sea veraz, pero nada lo valida. |
| `aggregation` | `all_required` (por defecto) o `any_healthy`. Determina cómo se combinan los contenedores observados para el estado agregado (`aggregate_status` en `application/policies/status.py`): con `all_required`, el servicio es `healthy` solo si **todos** los contenedores con `required: true` están corriendo (y sanos si Portainer reporta healthcheck); con `any_healthy`, basta con que **alguno** de los contenedores observados esté corriendo y sano. En ambos casos, si el healthcheck externo (`health:`) declarado falla, el servicio baja a `degraded`/`down` según el caso. |
| `containers[].name` | Nombre **exacto** del contenedor en Docker (`docker ps --format '{{.Names}}'` en el nodo, o el nombre visible en Portainer). Es el único dato que el runner y el `StatusService` usan para localizar el contenedor dentro del `environment_id` declarado — no se acepta un ID de contenedor suministrado por el cliente en ningún punto del flujo. |
| `containers[].required` | Por defecto `true`. Si es `false`, el contenedor se observa e informa pero no cuenta para decidir si el servicio está `down` cuando `aggregation: all_required`. |
| `containers[].critical` | Por defecto `false`. Si es `true` y ese contenedor concreto no está corriendo, el servicio se marca `down` **incondicionalmente**, sin importar el valor de `aggregation` ni el estado de los demás contenedores. |

## `health`

```yaml
health:
  type: http
  url: https://openwebui.home.arpa/health
  expected_status: 200
  timeout_seconds: 5
```

| Campo | Descripción |
|---|---|
| `type` | `http` o `tcp` en el esquema (`Literal["http", "tcp"]`), pero **solo `http` está implementado**: `HttpHealthProber` (`adapters/outbound/health.py`) siempre hace una petición HTTP GET, cualquiera que sea el valor de `type`. Declarar `type: tcp` no lanza un error de validación ni hace un connect TCP real — hoy se comporta exactamente igual que `http`. No lo uses hasta que este ítem se implemente. |
| `url` | Debe ser `http`/`https` con hostname. Sujeta a defensa SSRF real (`validate_health_url`): se rechaza si el host es una IP (salvo que además termine en un sufijo permitido), si resuelve a loopback/link-local/rango privado, o si el hostname no termina en uno de los sufijos de `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (por defecto `.home.arpa`; ver `core/settings.py`). Esta es la **única** URL del catálogo que la API llega a solicitar por sí misma; `service_url`/`documentation_url` no pasan por aquí porque nunca se piden desde el servidor. |
| `expected_status` | Código HTTP considerado "sano" (100–599, por defecto `200`). |
| `timeout_seconds` | 1–60, por defecto `5`. |

## `grafana` / `loki`

Ambos son objetos **completamente libres** (`dict[str, Any]`, sin validación de forma ni de claves permitidas pese a lo que sugiera el nombre) que `resolve_links` (`application/policies/links.py`) usa para construir enlaces de solo-lectura hacia herramientas externas — no se llama al servidor de Grafana/Loki desde la API, así que tampoco pasan por la defensa SSRF.

```yaml
grafana:
  dashboard_uid: containers-overview
  variables:
    service: ollama-service
loki:
  query: '{compose_service="ollama"}'
```

- `grafana.dashboard_uid`: UID del panel en tu Grafana (visible en la URL del dashboard: `.../d/<uid>/...`). Se concatena literalmente en `{grafana_url}/d/{dashboard_uid}`.
- `grafana.variables`: pares clave/valor que se traducen en parámetros `var-<clave>=<valor>` de la URL — deben coincidir con los nombres de variable de plantilla definidos en ese dashboard concreto de Grafana, si no, Grafana simplemente los ignora.
- `loki.query`: expresión LogQL en bruto que se coloca como parámetro `left` de `{loki_url}/explore?...`. Sin escapado más allá del `urlencode` estándar.

`CAPATAZ_GRAFANA_URL`/`CAPATAZ_LOKI_URL`/`CAPATAZ_PORTAINER_URL` (variables de entorno, ver `core/settings.py`) deben estar configuradas para que estos enlaces se generen; si falta la URL base correspondiente, el enlace simplemente no aparece.

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
  operation: restart   # start | stop | restart | logs
  target: selected_containers   # único valor aceptado
```

`target` siempre debe ser el literal `selected_containers`: nunca se acepta un ID de contenedor específico desde el cliente/catálogo — el runner resuelve los contenedores reales a partir de `service.container_selectors` (el bloque `portainer.containers` de más arriba), nunca desde `config`.

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
