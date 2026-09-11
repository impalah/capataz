# YAML Catalog

*Language: **English** · [Español](05-yaml-catalog.es.md)*

The catalog is one declarative, version-controllable file that defines **resources** (encrypted credentials and files), **connectors** (typed connections to Portainer, Prometheus, Grafana, Loki, HTTP health checks, Ansible and SSH) and **services** with their actions — see [ADR 008](adr/008-connectors-and-resources.en.md). The root is:

```yaml
version: 2       # the only accepted value; a v1 file is rejected (see "Converting a v1 catalog")
resources: []    # optional
connectors: []   # optional
services: []
```

This document describes **each field exactly as it is implemented today**. The reference schema lives in `api/src/capataz_api/domain/specs/` (`resources.py`, `connectors.py`, `services.py`, `actions.py`) and `application/dto/catalog.py`; if anything here diverges from the code, the code wins. The same specs validate the REST API (`/services`, `/connectors`, `/resources`) and therefore the Catalog UI, so everything on this page applies there too.

Identifiers: a service `id` is an immutable slug (`^[a-z0-9][a-z0-9-]*$`) and the upsert key on every import — do not rename it to represent a different service; to replace a service, delete the old one and create a new one with a new `id`. Resource and connector ids follow `^[a-z0-9][a-z0-9_-]{0,127}$` (underscores allowed). Ids must be unique within each list.

## How an import works

1. The whole document is parsed and validated first: shapes, every reference (a connector's resources, a service's connectors and their capabilities, each action's `config` against its connector's type), the SSRF rules, and loading each resource's content — checked against both the document and what already exists in the database.
2. Only if everything is valid does it write, in order resources → connectors → services and actions, all or nothing.
3. The response lists `errors` and `warnings` with their YAML line, plus `counts` per kind (`created`/`updated`, and `unchanged` for resources).

An import only creates and updates; it never deletes what isn't in the file (see `docs/12-roadmap.md`, item 3).

## `resources`

```yaml
resources:
  - id: portainer_token
    type: secret
    description: Portainer API token (capataz user)
    source: { file: portainer_token }
  - id: homelab_known_hosts
    type: known_hosts
    source: { env: HOMELAB_KNOWN_HOSTS_B64, encoding: base64 }
  - id: ssh_mole_key
    type: ssh_private_key   # no source: it must already exist (uploaded from the UI)
```

| Field | Description |
|---|---|
| `id` | Reference id used by connectors. |
| `type` | `secret` (token/password), `ssh_private_key`, `known_hosts`, or `file` (generic). Connectors check it: an `ansible` connector's `private_key`, for example, must reference an `ssh_private_key`. |
| `description` | Free text shown in the UI. |
| `source` | Where the import reads the content from — see below. Optional. |

| `source` | Behaviour |
|---|---|
| `{file: name}` | Read from `CAPATAZ_RESOURCES_DIR` (default `/run/capataz-resources`; `./resources` in Compose). Relative path only, no `.`/`..` segments, and the resolved path (`realpath`) must stay inside that directory, so a symlink can't escape it. |
| `{env: VAR, encoding: plain\|base64}` | Read from an environment variable of the API process (`plain` by default). |
| `{base64: "..."}` | Inline content. For development/tests only: the import adds a warning, and with `CAPATAZ_ENV=production` it is rejected unless `CAPATAZ_ALLOW_INLINE_RESOURCES=true`. |
| *(omitted)* | The resource must already exist in the database — typically uploaded in **Catalog → Resources**. |

Content is at most 64 KiB and is encrypted before being stored. On re-import, a keyed fingerprint tells whether it changed: unchanged content is a no-op; changed content is re-encrypted and its `version` increases. Content never leaves the API — not in responses, audit records or the export.

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
    type: http   # config is optional: it inherits the global allow-list
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

Each connector has an `id`, a `type`, an optional `description`, and a `config` validated by type. Its **capabilities** decide what services may use it for:

| `type` | `config` | Resource fields | Capabilities | Used by |
|---|---|---|---|---|
| `portainer` | `url` (**https** only), `token`, `verify_tls` (default `true`) | `token` → `secret` | `status`, `actions` | API (status, links) and runner (actions) |
| `prometheus` | `url`, `token` (optional), `verify_tls` | `token` → `secret` | `metrics` | API |
| `grafana` | `url` | — | `dashboards` | API (only builds links) |
| `loki` | `url` | — | `logs` | API (only builds links) |
| `http` | `allowed_host_suffixes` (list), `verify_tls`, `default_timeout_seconds` (1–60, default 5) | — | `health` | API |
| `ansible` | `inventory` (`inventories/<name>.yml`, and it must be in the runner's `ALLOWED_INVENTORIES`), `user` (optional POSIX user), `private_key`, `known_hosts`, `vault_password` (optional) | `private_key` → `ssh_private_key`, `known_hosts` → `known_hosts`, `vault_password` → `secret` | `actions` | runner |
| `ssh` | `host` (hostname), `port` (default 22), `user` (POSIX user), `private_key`, `known_hosts` | `private_key` → `ssh_private_key`, `known_hosts` → `known_hosts` | `actions` | runner |

Every connector URL and SSH host must be inside `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (the global SSRF ceiling, default `.404labo.net`). An `http` connector's `allowed_host_suffixes` can only narrow that ceiling for the health checks that use it; a suffix outside it is rejected. A connector that services or actions still use cannot be deleted (`409`), and neither can a resource that a connector uses.

> A Prometheus behind a forward-auth proxy (e.g. an Authentik outpost) answers the API with a 302 to the login page; point the connector at an address that bypasses the proxy (the homelab uses `http://prometheus.404labo.net:9090`).

## Service fields

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string, slug | Yes | Immutable logical identifier, upsert key. |
| `name` | string | Yes | Name shown on the card and in detail headers. |
| `description` | string | No | Text under the name on the service card, shown on **a single line** with CSS ellipsis (`.service-card p` in `frontend/src/styles/app.scss`) — keep it short (one sentence). |
| `group_name` | free string | Yes | Grouping label. There is no `Group` entity or allow-list: the Dashboard's "Group" dropdown is populated from the distinct values among loaded services, so two services must spell the group *exactly* the same (case and accents included) to be grouped together. |
| `environment` | free string | Yes | Same as `group_name`, for the "Environment" filter. |
| `icon` | string | No | Ligature name from [Material Icons](https://fonts.google.com/icons?icon.set=Material+Icons), the font bundled by Quasar. **It must exist literally in that font** — an invalid name, or one from another set (Material Symbols, Outlined/Round...), isn't rejected, but the browser renders the raw text, which overflows the icon box and visually "escapes" the card. Confirm the name belongs to the classic **"Material Icons"** set before using it. |
| `tags` | list of slugs (`^[a-z0-9][a-z0-9_-]{0,31}$`), at most 20 | No | Shown as chips on the service card; the Dashboard filters by them (a service must carry every selected tag) and its search box matches them too. |
| `service_url` | http/https URL | No | "Open service" link. Only displayed — the API never requests it, so it doesn't go through the SSRF defense. |
| `documentation_url` | http/https URL | No | "Documentation" link. Same treatment as `service_url`. |
| `runtime` | object | No | Where the service runs, for container status and Portainer actions — see below. |
| `observability` | object | No | Health check, dashboards, logs and metrics — see below. |
| `maintenance` | boolean, default `false` | No | If `true`, the aggregate status is always forced to `maintenance` (`aggregate_status` in `application/policies/status.py`), without consulting Portainer or the health check. |
| `metadata` | free object | No | Arbitrary data bag, persisted and returned by the API but not read by any application logic nor shown in the frontend. |

## `runtime`

```yaml
# Standalone / docker-compose container
runtime:
  connector: portainer
  environment_id: "5"
  stack_name: homelab-ryzen
  aggregation: all_required
  containers:
    - { name: ollama, required: true, critical: false }
```

```yaml
# Docker Swarm service
runtime:
  connector: portainer
  environment_id: "7"
  stack_name: homelab-swarm
  services:
    - { name: authentik-server, replicas: 1 }
```

Optional: without `runtime` the service has no container status and cannot have actions on a Portainer connector. `connector` must have the `status` capability (a `portainer` connector). A runtime declares **exactly one** of `containers` or `services`, depending on how the service is deployed:

- `containers` — a standalone/Compose deployment where the container keeps a fixed, predictable name (`docker run --name ollama`, or a Compose `container_name:`), matched by exact name against Portainer's container listing.
- `services` — a Docker Swarm service (`docker stack deploy`). Swarm mangles container names per task/replica (`{stack}_{service}.{slot}.{task-id}`), so `services` matches Docker's stable Swarm **service** name (`{stack_name}_{name}`) through the Docker Engine Services API instead.

| Field | Description |
|---|---|
| `connector` | A connector with the `status` capability. |
| `environment_id` | Portainer's **endpoint ID**: the number Portainer assigns to each environment (UI **Environments**, or `GET {connector url}/api/endpoints` with the token). A number is accepted and stored as a string. It's used literally in `api/endpoints/{environment_id}/docker/...`, so a wrong value passes validation and fails at runtime against Portainer. |
| `stack_name` | With `containers`, purely informational (shown as "Stack: ..." in the service detail). With `services` it **is used**: each service is resolved as `{stack_name}_{name}`, exactly as `docker stack deploy -c file.yml {stack_name}` names it — a wrong `stack_name` means no service ever matches. |
| `aggregation` | `all_required` (default) or `any_healthy`. With `all_required` the service is `healthy` only if **every** entry with `required: true` is running (and healthy — for a Swarm service, running tasks match desired tasks); with `any_healthy`, one running and healthy entry is enough. Either way, a failing health check drops it to `degraded`/`down`. |
| `containers[].name` | The container's **exact** Docker name — the only data used to locate it within `environment_id`; a client-supplied container ID is never accepted anywhere. |
| `containers[].required` / `critical` | Defaults `true`/`false`. `required: false` observes and reports the container without counting it toward `down` under `all_required`. `critical: true` marks the service `down` whenever that container isn't running, regardless of `aggregation`. |
| `services[].name` | The Swarm service's short name, **without** the stack prefix (`authentik-server`, not `homelab-swarm_authentik-server`). |
| `services[].replicas` | 0–50, default `1`. What a `start` action scales the service back up to, and what "fully scaled" is compared against. A service rescaled outside Capataz is reset to this value by the next `start`/`restart` from Capataz. |
| `services[].required` / `critical` | Same semantics as for `containers[]`. |

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

| Field | Description |
|---|---|
| `connector` | A connector with the `health` capability (`http`). |
| `url` | `http`/`https` with a hostname, subject to the SSRF defense (`validate_outbound_url`): rejected if the host doesn't end in one of the allowed suffixes (the connector's narrowed list, or `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES`), or is an IP/loopback/link-local/private address. |
| `method` | `GET` (default) or `HEAD`. |
| `expected_status` | HTTP code considered healthy (100–599, default `200`). |
| `timeout_seconds` | 1–60, default `5`. |

### `dashboards`

```yaml
  dashboards:
    - label: grafana
      connector: grafana
      uid: homelab-generico
      slug: servicio-generico
      variables: { var-service: open-webui, kiosk: tv }
    - label: nodes
      connector: grafana
      url: /d/node-exporter?var-node=retaco
```

Each dashboard becomes a link, named after its `label` (unique per service, default `grafana`), in the service detail page. `connector` needs the `dashboards` capability; Grafana itself is never called by the API.

- The link is `{connector url}/d/{uid}[/{slug}]?{variables}`. `variables` are used verbatim as query parameters — nothing is auto-prefixed, so give Grafana's **full** parameter name (`var-service` for a template variable `service`, or a modifier like `kiosk: tv`).
- `url`, if set, wins over `uid`/`slug`/`variables`: an absolute `http(s)://` URL is used as is, a relative one is appended to the connector's URL.
- Each dashboard needs `uid` or `url`.

### `logs`

```yaml
  logs:
    connector: loki
    query: '{compose_service="open-webui"}'
```

`connector` needs the `logs` capability. The raw LogQL expression becomes the `left` parameter of a `{connector url}/explore?...` link; no escaping beyond standard URL encoding.

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

| Field | Description |
|---|---|
| `label` | Free text shown above the value on the card (1–100 chars), not localized. |
| `connector` | A connector with the `metrics` capability (`prometheus`). |
| `query` | The **complete** PromQL (1–2000 chars), run verbatim against `{connector url}/api/v1/query`. If Prometheus returns several series, they are summed. |

Metrics are queried by `StatusService` on every `refresh-status`, grouped per connector; if one connector fails, only its metrics come back empty. A service with no metrics shows no metrics row.

**Trust boundary:** `query` has no content validation beyond its length — it's trusted verbatim. That's intentional and safe because only `capataz-admin` can edit the catalog, and it's never derived from an execution request or other request-time input. Treat it like a playbook path: operator-authored config. See docs/06-security.md.

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

| Field | Description |
|---|---|
| `key` | Unique slug **per service** (`^[a-z0-9][a-z0-9-]*$`); identifies the action in the execution URL and the upsert. |
| `label` | Button text/tooltip on the card and the service/execution pages. |
| `description` | Persisted and returned by the API, but not shown in the current frontend. |
| `icon` | A Material Icons ligature, with the same caveat as the service `icon`. |
| `connector` | A connector with the `actions` capability (`portainer`, `ansible` or `ssh`). Its type decides the shape of `config` and which runner executor runs the action. There is no `action_type` field in the YAML: the API derives it from the connector and returns it read-only. |
| `risk_level` | `read`, `operate`, or `critical` — see the role table below; it decides the minimum role that can execute the action. |
| `requires_confirmation` | Boolean, default `false`. **Declared but not implemented**: it's persisted and returned, but no step of the execution flow reads it — the frontend asks for confirmation based on `risk_level === 'critical'` only. |
| `enabled` | Boolean, default `true`. If `false`, any execution attempt is rejected. |
| `unattended` | Boolean, default `false`. UI preference: if `true`, the frontend fires the action and stays on the current screen instead of navigating to the execution detail. Good for quick actions (`start`/`stop`/`restart`); leave it `false` when the output matters (`logs`, Ansible, SSH). |
| `config` | Validated by the connector's type, see below. It can never contain a `command` key. |
| `allowed_parameters_schema` | `{"properties": {"<param>": {"enum": [...]}}}`. If defined, it **is** enforced: any execution-time parameter (`params` of `POST .../execute`) missing from `properties` is rejected, and an `enum` restricts its value. `command`, `container_id`, `url` and `playbook_path` are always forbidden as parameters. Omitted (`{}`), the action accepts no parameters. |

### `config` for a `portainer` connector

```yaml
config:
  operation: restart            # start | stop | restart | logs
  target: selected_containers   # selected_containers | selected_services
```

Exactly this shape. The service must declare a `runtime` on **the same Portainer connector**, and `target` must match its selector kind (`selected_services` for `services`, `selected_containers` for `containers`) — a mismatch is rejected when validating. The runner resolves the real targets from the service's `runtime`, never from `config` or the client.

For `selected_services`, the operations map onto the Docker Swarm Services API: `restart` is a **force update** (like `docker service update --force`), `logs` aggregates every task's logs, and `stop`/`start` **scale replicas to 0 / back to the declared `services[].replicas`** — they never remove or recreate the service.

### `config` for an `ansible` connector

```yaml
config:
  playbook: playbooks/backup_service.yml
  limit: node-ai-01
  extra_vars: { service: open-webui }
  timeout_seconds: 600
```

The inventory, remote user and credentials come from the **connector** — an `inventory` key in the action is rejected. The values are checked against fixed allow-lists in the **runner** (`runner/src/capataz_runner/actions.py`), the source of truth:

| Field | Allow-list | Notes |
|---|---|---|
| `playbook` | `playbooks/restart_service.yml`, `playbooks/backup_service.yml`, `playbooks/check_connectivity.yml` (`ALLOWED_PLAYBOOKS`) | Exactly one of these. A new playbook needs adding to `runner/playbooks/` **and** to that constant (and to the frontend's list in `src/utils/catalog.ts`). |
| `limit` | Safe slug (`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$`), required | Must exist as a host/group in the connector's inventory. `inventories/homelab.yml` today only defines the placeholders `node-ai-01` and `node-gpu-01`. |
| `extra_vars` | Keys `service`, `backup_label` (`ALLOWED_EXTRA_VARS`), each a safe slug | Execution-time `params` may override them, within the same allow-list. |
| `timeout_seconds` | 1–900, default 300 | |

### `config` for an `ssh` connector

```yaml
config:
  command_id: disk_usage
  params: { path: /srv }
```

`command_id` must exist in `runner/ssh_commands.yml`, versioned with the runner — an action can never carry command text. Each command declares an argv whose `{param}` placeholders take a whole element, its parameters (each with a full-match `pattern` or an `enum`, optionally a `default`) and a timeout. Unknown parameters are rejected; execution-time `params` override the action's own. The runner shell-quotes every element and runs `ssh` with `BatchMode=yes`, `StrictHostKeyChecking=yes` and the connector's pinned `known_hosts`. The API only checks the shape (`command_id` slug, string params); a `command_id` or value outside the allow-list makes the execution `rejected` in the runner.

| `command_id` | Runs | Parameters |
|---|---|---|
| `uptime` | `uptime` | — |
| `memory` | `free -h` | — |
| `disk_usage` | `df -h {path}` | `path` (absolute path, default `/`) |
| `docker_ps` | `docker ps --format ...` | — |
| `systemd_status` | `systemctl status --no-pager --lines=20 {unit}` | `unit` (unit name) |

Adding a command means editing `runner/ssh_commands.yml` and rebuilding the runner image (and adding it to the frontend's `sshCommands` list for the form).

## Role Table by `risk_level`

`risk_level` is what the API uses in `authorize_action` (`application/policies/rbac.py`) to decide whether the authenticated user can execute that specific action.

| `risk_level` | Minimum role to **execute** | Additional requirement |
|---|---|---|
| `read` | `capataz-operator` | None. A read-only action (e.g. `logs`) doesn't open it up to `capataz-viewer`: every execution needs at least the operator role. |
| `operate` | `capataz-operator` | None. |
| `critical` | `capataz-admin` | The request must include `confirmation: true` and a non-empty `reason`, or the API rejects it (403). |

## Complete Example

`catalog/services.example.yaml` contains the homelab's real catalog (27 services, 5 connectors, 4 resources) and is the living reference — it's validated and imported against the real API, unlike the snippets on this page.

## Prohibitions

Don't put passwords, tokens, keys, Vault values or DSNs anywhere in the catalog except as a resource's development-only `base64` source; no free-form commands, `command` key, `shell`, unversioned playbooks, external inventories, client container IDs, or execution URLs. Validation rejects them — a syntactically valid YAML isn't therefore allowed.

## Import, Dry-run, and Export

- Startup: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. If set but the file is missing or invalid, startup/readiness fails explicitly. Resource `file` sources are resolved in the API container's `CAPATAZ_RESOURCES_DIR`.
- API: `POST /api/v1/catalog/import` with `{"yaml":"...","dry_run":true}` validates without writing; `dry_run=false` persists. The Catalog UI (**Import & export** tab) shows the errors and warnings with their line.
- CLI: `make seed-catalog` imports the example through the API.
- Export: `GET /api/v1/catalog/export` or `make export-catalog > catalog/export.yaml`. Resources appear as metadata plus their `file`/`env` source only — never content, never an inline literal; a resource uploaded from the UI is exported without `source`, so importing that export elsewhere requires uploading it there first.

## Converting a v1 Catalog

A `version: 1` file is rejected. Convert it with:

```bash
uv run --project api python scripts/convert_catalog_v1_to_v2.py catalog/v1.yaml -o catalog/v2.yaml
```

The script creates the `portainer`, `prometheus`, `grafana`, `loki`, `http` and `ansible` connectors (homelab default URLs, see `--help`), resources with `{file: <old Docker secret name>}` sources (`portainer_token`, `runner_ssh_private_key`, `runner_known_hosts`, `ansible_vault_password` — put those files in `CAPATAZ_RESOURCES_DIR`), and moves each service's inline blocks into `runtime`/`observability`. Its ids match the placeholder connectors created by migration `0009`, so importing the converted catalog replaces them in place. Dry-run the result before importing it.

## Common Errors

- **Duplicate id / key**: ids must be unique per list, action keys per service.
- **Unknown connector or wrong capability**: e.g. `runtime.connector` pointing at a `grafana` connector, or an action on a `prometheus` connector.
- **Resource missing or of the wrong type**: a connector field references a resource that neither the document nor the database has, or one of another type (`private_key` must be an `ssh_private_key`).
- **URL or host rejected**: outside the suffix allow-list, an IP, or a Portainer URL that isn't `https`. `service_url`/`documentation_url` are never rejected for this, since they're never requested.
- **Portainer action rejected**: the service has no `runtime`, its runtime uses another connector, or `target` doesn't match the selector kind.
- **Invalid `ansible` action**: playbook outside `ALLOWED_PLAYBOOKS`, an `inventory` key in the action, missing or invalid `limit`, an `extra_vars` key outside `ALLOWED_EXTRA_VARS`, or `timeout_seconds` outside 1–900.
- **`ssh` execution rejected**: `command_id` not in `runner/ssh_commands.yml`, an unknown parameter, or a value that doesn't match its pattern.
- **Inline resource in production**: use a `file`/`env` source or upload it from the UI, or set `CAPATAZ_ALLOW_INLINE_RESOURCES=true` knowingly.
- **Resource file not found**: the file isn't in the API container's `CAPATAZ_RESOURCES_DIR`, or the path tries to leave it.
- **`version: 1`**: convert the file (above).
- **Icon that doesn't show or overflows the card**: the name doesn't exist in the bundled Material Icons font.
