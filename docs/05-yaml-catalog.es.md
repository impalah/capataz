# Catálogo YAML

*Idioma: **Español** · [English](05-yaml-catalog.en.md)*

El catálogo es un único fichero declarativo y versionable que define **recursos** (credenciales y ficheros cifrados), **conectores** (conexiones tipadas a Portainer, Prometheus, Grafana, Loki, health checks HTTP, Ansible y SSH) y **servicios** con sus acciones — ver [ADR 008](adr/008-connectors-and-resources.es.md). La raíz es:

```yaml
version: 2       # único valor aceptado; un fichero v1 se rechaza (ver "Convertir un catálogo v1")
resources: []    # opcional
connectors: []   # opcional
services: []
```

Este documento describe **cada campo tal y como está implementado hoy**. El esquema de referencia vive en `api/src/capataz_api/domain/specs/` (`resources.py`, `connectors.py`, `services.py`, `actions.py`) y `application/dto/catalog.py`; si algo aquí y el código divergen, el código manda. Los mismos specs validan la API REST (`/services`, `/connectors`, `/resources`) y por tanto la UI del catálogo, así que todo lo de esta página aplica también allí.

Identificadores: el `id` de un servicio es un slug inmutable (`^[a-z0-9][a-z0-9-]*$`) y la clave de upsert en cada importación — no lo renombres para representar otro servicio; para sustituir un servicio, borra el antiguo y crea uno con `id` nuevo. Los ids de recursos y conectores siguen `^[a-z0-9][a-z0-9_-]{0,127}$` (admiten guion bajo). Los ids tienen que ser únicos dentro de cada lista.

## Cómo funciona una importación

1. Primero se analiza y valida el documento entero: formas, todas las referencias (los recursos de un conector, los conectores de un servicio y sus capacidades, el `config` de cada acción frente al tipo de su conector), las reglas SSRF y la carga del contenido de cada recurso — contra el propio documento y contra lo que ya existe en la base de datos.
2. Solo si todo es válido se escribe, en orden recursos → conectores → servicios y acciones, todo o nada.
3. La respuesta enumera `errors` y `warnings` con su línea del YAML, más `counts` por tipo (`created`/`updated`, y `unchanged` para los recursos).

Una importación solo crea y actualiza; nunca borra lo que no está en el fichero (ver `docs/12-roadmap.md`, punto 3).

## `resources`

```yaml
resources:
  - id: portainer_token
    type: secret
    description: Token de la API de Portainer (usuario capataz)
    source: { file: portainer_token }
  - id: homelab_known_hosts
    type: known_hosts
    source: { env: HOMELAB_KNOWN_HOSTS_B64, encoding: base64 }
  - id: ssh_mole_key
    type: ssh_private_key   # sin source: tiene que existir ya (subido desde la UI)
```

| Campo | Descripción |
|---|---|
| `id` | Id de referencia que usan los conectores. |
| `type` | `secret` (token/contraseña), `ssh_private_key`, `known_hosts` o `file` (genérico). Los conectores lo comprueban: el `private_key` de un conector `ansible`, por ejemplo, tiene que referenciar un `ssh_private_key`. |
| `description` | Texto libre que se muestra en la UI. |
| `source` | De dónde lee la importación el contenido — ver abajo. Opcional. |

| `source` | Comportamiento |
|---|---|
| `{file: nombre}` | Se lee de `CAPATAZ_RESOURCES_DIR` (por defecto `/run/capataz-resources`; `./resources` en Compose). Solo ruta relativa, sin segmentos `.`/`..`, y la ruta resuelta (`realpath`) tiene que quedar dentro de ese directorio, así que un symlink no puede escapar de él. |
| `{env: VAR, encoding: plain\|base64}` | Se lee de una variable de entorno del proceso de la API (`plain` por defecto). |
| `{base64: "..."}` | Contenido en el propio YAML. Solo para desarrollo/pruebas: la importación añade un aviso y, con `CAPATAZ_ENV=production`, se rechaza salvo que `CAPATAZ_ALLOW_INLINE_RESOURCES=true`. |
| *(omitido)* | El recurso tiene que existir ya en la base de datos — normalmente subido en **Catálogo → Recursos**. |

El contenido tiene como máximo 64 KiB y se cifra antes de guardarse. Al reimportar, una huella con clave indica si cambió: si no cambió, no se hace nada; si cambió, se vuelve a cifrar y su `version` aumenta. El contenido nunca sale de la API — ni en respuestas, ni en la auditoría, ni en la exportación.

## `connectors`

```yaml
connectors:
  - id: portainer
    type: portainer
    config: { url: https://portainer.404labo.net, token: portainer_token }
  - id: prometheus
    type: prometheus
    config: { url: http://prometheus.404labo.net:9090 }
  - id: grafana
    type: grafana
    config: { url: https://grafana.404labo.net }
  - id: loki
    type: loki
    config: { url: https://loki.404labo.net }
  - id: http
    type: http   # config opcional: hereda la allow-list global
  - id: ansible
    type: ansible
    config:
      inventory: inventories/homelab.yml
      private_key: runner_ssh_private_key
      known_hosts: runner_known_hosts
      vault_password: ansible_vault_password
  - id: ssh_mole
    type: ssh
    config: { host: mole.404labo.net, user: capataz, private_key: ssh_mole_key, known_hosts: homelab_known_hosts }
```

Cada conector tiene `id`, `type`, `description` opcional y un `config` validado según el tipo. Sus **capacidades** deciden para qué pueden usarlo los servicios:

| `type` | `config` | Campos de recurso | Capacidades | Lo usa |
|---|---|---|---|---|
| `portainer` | `url` (solo **https**), `token`, `verify_tls` (por defecto `true`) | `token` → `secret` | `status`, `actions` | API (estado, enlaces) y runner (acciones) |
| `prometheus` | `url`, `token` (opcional), `verify_tls` | `token` → `secret` | `metrics` | API |
| `grafana` | `url` | — | `dashboards` | API (solo construye enlaces) |
| `loki` | `url` | — | `logs` | API (solo construye enlaces) |
| `http` | `allowed_host_suffixes` (lista), `verify_tls`, `default_timeout_seconds` (1–60, por defecto 5) | — | `health` | API |
| `ansible` | `inventory` (`inventories/<nombre>.yml`, y tiene que estar en `ALLOWED_INVENTORIES` del runner), `user` (usuario POSIX opcional), `private_key`, `known_hosts`, `vault_password` (opcional) | `private_key` → `ssh_private_key`, `known_hosts` → `known_hosts`, `vault_password` → `secret` | `actions` | runner |
| `ssh` | `host` (hostname), `port` (por defecto 22), `user` (usuario POSIX), `private_key`, `known_hosts` | `private_key` → `ssh_private_key`, `known_hosts` → `known_hosts` | `actions` | runner |

Toda URL de conector y todo host SSH tiene que estar dentro de `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (el techo global SSRF, por defecto `.404labo.net`). El `allowed_host_suffixes` de un conector `http` solo puede restringir ese techo para los health checks que lo usan; un sufijo fuera de él se rechaza. No se puede borrar un conector que aún usan servicios o acciones (`409`), ni un recurso que usa un conector.

> Un Prometheus detrás de un proxy de forward-auth (p. ej. un outpost de Authentik) responde a la API con un 302 a la página de login; apunta el conector a una dirección que se salte el proxy (el homelab usa `http://prometheus.404labo.net:9090`).

## Campos de servicio

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | string, slug | Sí | Identificador lógico inmutable, clave de upsert. |
| `name` | string | Sí | Nombre en la tarjeta y en las cabeceras de detalle. |
| `description` | string | No | Texto bajo el nombre en la tarjeta, mostrado en **una sola línea** con elipsis CSS (`.service-card p` en `frontend/src/styles/app.scss`) — mantenlo corto (una frase). |
| `group_name` | string libre | Sí | Etiqueta de agrupación. No hay entidad `Group` ni allow-list: el desplegable "Grupo" del Dashboard se rellena con los valores distintos de los servicios cargados, así que dos servicios tienen que escribir el grupo *exactamente* igual (mayúsculas y tildes incluidas) para agruparse. |
| `environment` | string libre | Sí | Igual que `group_name`, para el filtro "Entorno". |
| `icon` | string | No | Nombre de ligadura de [Material Icons](https://fonts.google.com/icons?icon.set=Material+Icons), la fuente que incluye Quasar. **Tiene que existir literalmente en esa fuente** — un nombre inválido, o de otro set (Material Symbols, Outlined/Round...), no se rechaza, pero el navegador pinta el texto en bruto, que desborda la caja del icono y se "sale" de la tarjeta. Confirma que el nombre pertenece al set clásico **"Material Icons"** antes de usarlo. |
| `tags` | lista de slugs (`^[a-z0-9][a-z0-9_-]{0,31}$`), máximo 20 | No | Se muestran como chips en la tarjeta; el Dashboard filtra por ellos (un servicio tiene que llevar todos los tags seleccionados) y su buscador también los tiene en cuenta. |
| `service_url` | URL http/https | No | Enlace "Abrir servicio". Solo se muestra — la API nunca lo solicita, así que no pasa por la defensa SSRF. |
| `documentation_url` | URL http/https | No | Enlace de documentación. Mismo tratamiento que `service_url`. |
| `runtime` | objeto | No | Dónde se ejecuta el servicio, para el estado de contenedores y las acciones Portainer — ver abajo. |
| `observability` | objeto | No | Health check, dashboards, logs y métricas — ver abajo. |
| `maintenance` | booleano, por defecto `false` | No | Si es `true`, el estado agregado se fuerza siempre a `maintenance` (`aggregate_status` en `application/policies/status.py`), sin consultar Portainer ni el health check. |
| `metadata` | objeto libre | No | Bolsa de datos arbitraria, persistida y devuelta por la API, pero que ninguna lógica lee ni el frontend muestra. |

## `runtime`

```yaml
# Contenedor standalone / docker-compose
runtime:
  connector: portainer
  environment_id: "5"
  stack_name: homelab-ryzen
  aggregation: all_required
  containers:
    - { name: ollama, required: true, critical: false }
```

```yaml
# Servicio Docker Swarm
runtime:
  connector: portainer
  environment_id: "7"
  stack_name: homelab-swarm
  services:
    - { name: authentik-server, replicas: 1 }
```

Opcional: sin `runtime` el servicio no tiene estado de contenedores ni puede tener acciones sobre un conector Portainer. `connector` tiene que tener la capacidad `status` (un conector `portainer`). Un runtime declara **exactamente uno** de `containers` o `services`, según cómo se despliegue el servicio:

- `containers` — un despliegue standalone/Compose cuyo contenedor mantiene un nombre fijo y predecible (`docker run --name ollama`, o un `container_name:` de Compose), buscado por nombre exacto en el listado de contenedores de Portainer.
- `services` — un servicio Docker Swarm (`docker stack deploy`). Swarm cambia el nombre del contenedor por tarea/réplica (`{stack}_{service}.{slot}.{task-id}`), así que `services` busca el nombre estable del **servicio** Swarm (`{stack_name}_{name}`) a través de la API de Services de Docker Engine.

| Campo | Descripción |
|---|---|
| `connector` | Un conector con la capacidad `status`. |
| `environment_id` | El **endpoint ID** de Portainer: el número que Portainer asigna a cada entorno (UI **Environments**, o `GET {url del conector}/api/endpoints` con el token). Se acepta un número y se guarda como string. Se usa literalmente en `api/endpoints/{environment_id}/docker/...`, así que un valor erróneo pasa la validación y falla en ejecución contra Portainer. |
| `stack_name` | Con `containers`, puramente informativo (se muestra como "Stack: ..." en el detalle). Con `services` **sí se usa**: cada servicio se resuelve como `{stack_name}_{name}`, igual que lo nombra `docker stack deploy -c fichero.yml {stack_name}` — un `stack_name` erróneo hace que ningún servicio coincida. |
| `aggregation` | `all_required` (por defecto) o `any_healthy`. Con `all_required` el servicio está `healthy` solo si **todas** las entradas con `required: true` están en ejecución (y sanas — en un servicio Swarm, tareas en ejecución = tareas deseadas); con `any_healthy` basta con una en ejecución y sana. En ambos casos, un health check fallido lo baja a `degraded`/`down`. |
| `containers[].name` | El nombre **exacto** del contenedor en Docker — el único dato con el que se localiza dentro de `environment_id`; nunca se acepta un ID de contenedor aportado por el cliente. |
| `containers[].required` / `critical` | Por defecto `true`/`false`. `required: false` observa y muestra el contenedor sin contarlo para `down` con `all_required`. `critical: true` marca el servicio `down` siempre que ese contenedor no esté en ejecución, sea cual sea `aggregation`. |
| `services[].name` | Nombre corto del servicio Swarm, **sin** el prefijo del stack (`authentik-server`, no `homelab-swarm_authentik-server`). |
| `services[].replicas` | 0–50, por defecto `1`. A cuántas réplicas vuelve a escalar una acción `start`, y con qué se compara "totalmente escalado". Un servicio reescalado fuera de Capataz vuelve a este valor con el siguiente `start`/`restart` desde Capataz. |
| `services[].required` / `critical` | Misma semántica que en `containers[]`. |

## `observability`

### `health`

```yaml
observability:
  health:
    connector: http
    url: https://openwebui.404labo.net/health
    method: GET
    expected_status: 200
    timeout_seconds: 5
```

| Campo | Descripción |
|---|---|
| `connector` | Un conector con la capacidad `health` (`http`). |
| `url` | `http`/`https` con hostname, sujeta a la defensa SSRF (`validate_outbound_url`): se rechaza si el host no termina en uno de los sufijos permitidos (la lista restringida del conector, o `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES`), o es una IP/loopback/link-local/dirección privada. |
| `method` | `GET` (por defecto) o `HEAD`. |
| `expected_status` | Código HTTP que se considera sano (100–599, por defecto `200`). |
| `timeout_seconds` | 1–60, por defecto `5`. |

### `dashboards`

```yaml
  dashboards:
    - label: grafana
      connector: grafana
      uid: homelab-generico
      slug: servicio-generico
      variables: { var-service: open-webui, kiosk: tv }
    - label: nodos
      connector: grafana
      url: /d/node-exporter?var-node=retaco
```

Cada dashboard se convierte en un enlace, con el nombre de su `label` (único por servicio, por defecto `grafana`), en la página de detalle del servicio. `connector` necesita la capacidad `dashboards`; la API nunca llama a Grafana.

- El enlace es `{url del conector}/d/{uid}[/{slug}]?{variables}`. Las `variables` se usan tal cual como parámetros de query — no se añade ningún prefijo, así que indica el nombre **completo** que espera Grafana (`var-service` para una variable de plantilla `service`, o un modificador como `kiosk: tv`).
- `url`, si se indica, manda sobre `uid`/`slug`/`variables`: una URL absoluta `http(s)://` se usa tal cual, una relativa se añade a la URL del conector.
- Cada dashboard necesita `uid` o `url`.

### `logs`

```yaml
  logs:
    connector: loki
    query: '{compose_service="open-webui"}'
```

`connector` necesita la capacidad `logs`. La expresión LogQL en bruto es el parámetro `left` de un enlace `{url del conector}/explore?...`; sin más escape que el URL encoding estándar.

### `metrics`

```yaml
  metrics:
    - label: CPU
      connector: prometheus
      query: 'avg(rate(container_cpu_usage_seconds_total{container_label_com_docker_stack_namespace="ollama-service"}[30s])) * 100'
    - label: Memoria
      connector: prometheus
      query: 'avg(container_memory_working_set_bytes{container_label_com_docker_stack_namespace="ollama-service"}) / 1024 / 1024'
```

| Campo | Descripción |
|---|---|
| `label` | Texto libre sobre el valor en la tarjeta (1–100 caracteres), sin localizar. |
| `connector` | Un conector con la capacidad `metrics` (`prometheus`). |
| `query` | El PromQL **completo** (1–2000 caracteres), ejecutado tal cual contra `{url del conector}/api/v1/query`. Si Prometheus devuelve varias series, se suman. |

`StatusService` consulta las métricas en cada `refresh-status`, agrupadas por conector; si falla un conector, solo sus métricas vuelven vacías. Un servicio sin métricas no muestra la fila de métricas.

**Límite de confianza:** `query` no tiene más validación de contenido que su longitud — se confía en ella tal cual. Es intencionado y seguro porque solo `capataz-admin` puede editar el catálogo, y nunca se deriva de una petición de ejecución ni de otro input en tiempo de petición. Trátala como la ruta de un playbook: configuración escrita por el operador. Ver docs/06-security.md.

## `actions`

```yaml
    actions:
      - key: restart
        label: Reiniciar
        icon: restart_alt
        connector: portainer
        risk_level: operate
        unattended: true
        config: { operation: restart, target: selected_containers }
      - key: backup
        label: Copia de seguridad
        connector: ansible
        risk_level: critical
        config:
          playbook: playbooks/backup_service.yml
          limit: node-ai-01
          extra_vars: { service: open-webui }
          timeout_seconds: 600
      - key: disk
        label: Disco
        connector: ssh_mole
        risk_level: read
        config: { command_id: disk_usage, params: { path: /srv } }
```

| Campo | Descripción |
|---|---|
| `key` | Slug único **por servicio** (`^[a-z0-9][a-z0-9-]*$`); identifica la acción en la URL de ejecución y en el upsert. |
| `label` | Texto del botón/tooltip en la tarjeta y en las páginas de servicio/ejecución. |
| `description` | Se persiste y la API la devuelve, pero el frontend actual no la muestra. |
| `icon` | Ligadura de Material Icons, con la misma salvedad que el `icon` del servicio. |
| `connector` | Un conector con la capacidad `actions` (`portainer`, `ansible` o `ssh`). Su tipo decide la forma de `config` y qué ejecutor del runner la ejecuta. En el YAML no hay campo `action_type`: la API lo deriva del conector y lo devuelve como solo lectura. |
| `risk_level` | `read`, `operate` o `critical` — ver la tabla de roles; decide el rol mínimo que puede ejecutar la acción. |
| `requires_confirmation` | Booleano, por defecto `false`. **Declarado pero no implementado**: se persiste y se devuelve, pero ningún paso del flujo de ejecución lo lee — el frontend pide confirmación solo según `risk_level === 'critical'`. |
| `enabled` | Booleano, por defecto `true`. Si es `false`, se rechaza cualquier intento de ejecución. |
| `unattended` | Booleano, por defecto `false`. Preferencia de UI: si es `true`, el frontend lanza la acción y se queda en la pantalla actual en vez de navegar al detalle de la ejecución. Útil para acciones rápidas (`start`/`stop`/`restart`); déjalo en `false` cuando importa la salida (`logs`, Ansible, SSH). |
| `config` | Validado según el tipo del conector, ver abajo. Nunca puede contener la clave `command`. |
| `allowed_parameters_schema` | `{"properties": {"<param>": {"enum": [...]}}}`. Si se define, **sí** se aplica: cualquier parámetro de ejecución (`params` de `POST .../execute`) que no esté en `properties` se rechaza, y un `enum` restringe su valor. `command`, `container_id`, `url` y `playbook_path` están siempre prohibidos como parámetros. Si se omite (`{}`), la acción no admite parámetros. |

### `config` para un conector `portainer`

```yaml
config:
  operation: restart            # start | stop | restart | logs
  target: selected_containers   # selected_containers | selected_services
```

Exactamente esta forma. El servicio tiene que declarar un `runtime` sobre **el mismo conector Portainer**, y `target` tiene que coincidir con su tipo de selector (`selected_services` para `services`, `selected_containers` para `containers`) — si no, se rechaza al validar. El runner resuelve los objetivos reales a partir del `runtime` del servicio, nunca de `config` ni del cliente.

Con `selected_services`, las operaciones se traducen a la API de Services de Docker Swarm: `restart` es un **force update** (como `docker service update --force`), `logs` agrega los logs de todas las tareas, y `stop`/`start` **escalan las réplicas a 0 / de vuelta a las `services[].replicas` declaradas** — nunca borran ni recrean el servicio.

### `config` para un conector `ansible`

```yaml
config:
  playbook: playbooks/backup_service.yml
  limit: node-ai-01
  extra_vars: { service: open-webui }
  timeout_seconds: 600
```

El inventario, el usuario remoto y las credenciales vienen del **conector** — una clave `inventory` en la acción se rechaza. Los valores se comprueban contra allow-lists fijas del **runner** (`runner/src/capataz_runner/actions.py`), que es la fuente de verdad:

| Campo | Allow-list | Notas |
|---|---|---|
| `playbook` | `playbooks/restart_service.yml`, `playbooks/backup_service.yml`, `playbooks/check_connectivity.yml` (`ALLOWED_PLAYBOOKS`) | Exactamente uno de estos. Un playbook nuevo hay que añadirlo a `runner/playbooks/` **y** a esa constante (y a la lista del frontend en `src/utils/catalog.ts`). |
| `limit` | Slug seguro (`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$`), obligatorio | Tiene que existir como host/grupo en el inventario del conector. `inventories/homelab.yml` hoy solo define los marcadores `node-ai-01` y `node-gpu-01`. |
| `extra_vars` | Claves `service`, `backup_label` (`ALLOWED_EXTRA_VARS`), cada una un slug seguro | Los `params` de ejecución pueden sobrescribirlas, dentro de la misma allow-list. |
| `timeout_seconds` | 1–900, por defecto 300 | |

### `config` para un conector `ssh`

```yaml
config:
  command_id: disk_usage
  params: { path: /srv }
```

`command_id` tiene que existir en `runner/ssh_commands.yml`, versionado con el runner — una acción nunca puede llevar texto de comando. Cada comando declara un argv cuyos marcadores `{param}` ocupan un elemento entero, sus parámetros (cada uno con un `pattern` de coincidencia completa o un `enum`, y opcionalmente un `default`) y un timeout. Los parámetros desconocidos se rechazan; los `params` de ejecución sobrescriben los de la acción. El runner entrecomilla cada elemento y ejecuta `ssh` con `BatchMode=yes`, `StrictHostKeyChecking=yes` y el `known_hosts` fijado del conector. La API solo comprueba la forma (`command_id` slug, parámetros string); un `command_id` o un valor fuera de la allow-list deja la ejecución `rejected` en el runner.

| `command_id` | Ejecuta | Parámetros |
|---|---|---|
| `uptime` | `uptime` | — |
| `memory` | `free -h` | — |
| `disk_usage` | `df -h {path}` | `path` (ruta absoluta, por defecto `/`) |
| `docker_ps` | `docker ps --format ...` | — |
| `systemd_status` | `systemctl status --no-pager --lines=20 {unit}` | `unit` (nombre de la unidad) |

Añadir un comando supone editar `runner/ssh_commands.yml` y reconstruir la imagen del runner (y añadirlo a la lista `sshCommands` del frontend para el formulario).

## Tabla de roles por `risk_level`

`risk_level` es lo que la API usa en `authorize_action` (`application/policies/rbac.py`) para decidir si el usuario autenticado puede ejecutar esa acción concreta.

| `risk_level` | Rol mínimo para **ejecutar** | Requisito adicional |
|---|---|---|
| `read` | `capataz-operator` | Ninguno. Que una acción sea de solo lectura (p. ej. `logs`) no la abre a `capataz-viewer`: toda ejecución requiere al menos el rol operator. |
| `operate` | `capataz-operator` | Ninguno. |
| `critical` | `capataz-admin` | La petición tiene que incluir `confirmation: true` y un `reason` no vacío, o la API la rechaza (403). |

## Ejemplo completo

`catalog/services.example.yaml` contiene el catálogo real del homelab (27 servicios, 5 conectores, 4 recursos) y es la referencia viva — se valida e importa contra la API real, a diferencia de los fragmentos de esta página.

## Prohibiciones

No pongas contraseñas, tokens, claves, valores de Vault ni DSNs en ningún sitio del catálogo salvo como origen `base64` de un recurso, solo en desarrollo; tampoco comandos libres, la clave `command`, `shell`, playbooks no versionados, inventarios externos, IDs de contenedor de cliente ni URLs de ejecución. La validación los rechaza — que el YAML sea sintácticamente válido no lo hace admisible.

## Importación, dry-run y exportación

- Arranque: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. Si se indica pero el fichero falta o no valida, el arranque/readiness falla explícitamente. Los orígenes `file` de los recursos se resuelven en el `CAPATAZ_RESOURCES_DIR` del contenedor de la API.
- API: `POST /api/v1/catalog/import` con `{"yaml":"...","dry_run":true}` valida sin escribir; `dry_run=false` persiste. La UI del catálogo (pestaña **Importar y exportar**) muestra los errores y avisos con su línea.
- CLI: `make seed-catalog` importa el ejemplo a través de la API.
- Exportación: `GET /api/v1/catalog/export` o `make export-catalog > catalog/export.yaml`. Los recursos aparecen como metadatos más su origen `file`/`env` — nunca el contenido ni un literal en el YAML; un recurso subido desde la UI se exporta sin `source`, así que importar esa exportación en otro sitio exige subirlo allí antes.

## Convertir un catálogo v1

Un fichero `version: 1` se rechaza. Conviértelo con:

```bash
uv run --project api python scripts/convert_catalog_v1_to_v2.py catalog/v1.yaml -o catalog/v2.yaml
```

El script crea los conectores `portainer`, `prometheus`, `grafana`, `loki`, `http` y `ansible` (URLs por defecto del homelab, ver `--help`), recursos con orígenes `{file: <nombre del antiguo Docker secret>}` (`portainer_token`, `runner_ssh_private_key`, `runner_known_hosts`, `ansible_vault_password` — pon esos ficheros en `CAPATAZ_RESOURCES_DIR`), y mueve los bloques de cada servicio a `runtime`/`observability`. Sus ids coinciden con los conectores provisionales que crea la migración `0009`, así que importar el catálogo convertido los sustituye in situ. Valida el resultado en dry-run antes de importarlo.

## Errores comunes

- **ID / clave duplicados**: los ids tienen que ser únicos por lista, las claves de acción por servicio.
- **Conector desconocido o sin la capacidad**: p. ej. `runtime.connector` apuntando a un conector `grafana`, o una acción sobre un conector `prometheus`.
- **Recurso inexistente o de otro tipo**: un campo de conector referencia un recurso que no está ni en el documento ni en la base de datos, o uno de otro tipo (`private_key` tiene que ser un `ssh_private_key`).
- **URL o host rechazados**: fuera de la allow-list de sufijos, una IP, o una URL de Portainer que no es `https`. `service_url`/`documentation_url` nunca se rechazan por esto, porque nunca se solicitan.
- **Acción Portainer rechazada**: el servicio no tiene `runtime`, su runtime usa otro conector, o `target` no coincide con el tipo de selector.
- **Acción `ansible` inválida**: playbook fuera de `ALLOWED_PLAYBOOKS`, una clave `inventory` en la acción, `limit` ausente o inválido, una clave de `extra_vars` fuera de `ALLOWED_EXTRA_VARS`, o `timeout_seconds` fuera de 1–900.
- **Ejecución `ssh` rechazada**: `command_id` que no está en `runner/ssh_commands.yml`, un parámetro desconocido, o un valor que no cumple su patrón.
- **Recurso en el YAML en producción**: usa un origen `file`/`env` o súbelo desde la UI, o fija `CAPATAZ_ALLOW_INLINE_RESOURCES=true` a sabiendas.
- **Fichero de recurso no encontrado**: el fichero no está en el `CAPATAZ_RESOURCES_DIR` del contenedor de la API, o la ruta intenta salir de él.
- **`version: 1`**: convierte el fichero (arriba).
- **Icono que no aparece o desborda la tarjeta**: el nombre no existe en la fuente Material Icons incluida.
