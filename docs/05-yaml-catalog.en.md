# YAML Catalog

*Language: **English** · [Español](05-yaml-catalog.es.md)*

The catalog is a declarative, version-controllable, secret-free way to define services and actions. The root contains `version: 1` (the only accepted value) and `services` (a list). Each service's `id` is an immutable logical slug (`^[a-z0-9][a-z0-9-]*$`) that serves as the upsert key on every import — do not rename it to represent a different service; if you need to replace a service, delete the old one and create a new one with a new `id`.

This document describes **each field exactly as it is implemented today**, with its real validation and, where applicable, where the value comes from. The reference schema lives in `api/src/capataz_api/application/dto/catalog.py` (`Catalog`/`ServiceCatalog`/`ActionCatalog`); if anything here diverges from the code, the code wins.

## Service Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string, slug | Yes | Immutable logical identifier, upsert key. |
| `name` | string | Yes | Name shown on the card and in detail headers. |
| `description` | string | No | Text under the name on the service card. It is shown on **a single line** with CSS ellipsis (`.service-card p` in `frontend/src/styles/app.scss`) — a long description gets visually truncated, so it's best kept short (one sentence). |
| `group_name` | free string | Yes | Grouping label. There is no `Group` entity or allow-list: it's a loose `str` on `Service` (`domain/entities/models.py`). The Dashboard's "Group" dropdown (`DashboardPage.vue`) is populated from the distinct values found among already-loaded services — two services must write the group name *exactly* the same (including case/accents) to be grouped together. |
| `environment` | free string | Yes | Same as `group_name` but for the "Environment" filter: a free string with no allow-list, used only for visual grouping (the example catalog uses `homelab` for all of them). |
| `icon` | string | No | Ligature name from [Material Icons](https://fonts.google.com/icons?icon.set=Material+Icons), the font bundled by Quasar (`@quasar/extras/material-icons`). **It must exist literally in that font** — an invalid name, or one from a different set (Material Symbols, Icons Outlined/Round, etc.), does not raise any validation error: the catalog accepts it as-is, but in the browser the ligature does not replace the text and the `<i>` renders the raw string, overflowing the icon's 28px box (visible as `scrollWidth` > `offsetWidth` when inspecting the element) and visually "escaping" the card. Before using a new name, open it on Google's own page and confirm it belongs to the **"Material Icons"** set (the classic filled one), not Symbols/Outlined/Round. |
| `service_url` | http/https URL | No | "Open service" link. It's exposed as-is to the frontend (`resolve_links` in `application/policies/links.py`) — the API never makes an HTTP request to this URL, so it doesn't go through the SSRF defense (that only applies to `health.url`, see below). |
| `documentation_url` | http/https URL | No | "Documentation" link. Same treatment as `service_url`: it's only displayed, never called from the server. |
| `maintenance` | boolean, defaults to `false` | No | If `true`, the service's aggregate status is always forced to `maintenance` (see `aggregate_status` in `application/policies/status.py`), without consulting Portainer or the healthcheck. **It is not exposed in the "New service"/"Edit service" form of `CatalogPage.vue`** — it can only be set by importing YAML or calling the raw API (`PATCH /services/{id}`). |
| `metadata` | free object | No | Arbitrary data bag, persisted and exposed as-is by the API (`GET /services/{id}`), but **not read by any application logic nor shown in the frontend** today. Useful as your own annotation or for future integrations, with no current functional effect. |

## `portainer`

A service declares **exactly one** of `containers` or `services` (never both, never neither — enforced by `PortainerCatalog`'s own validator) depending on how it's deployed:

- `containers` — a standalone/Compose deployment where the container keeps a fixed, predictable name (e.g. `docker run --name ollama` or a Compose `container_name:`). Matched against Portainer's raw container listing by exact name.
- `services` — a Docker Swarm service (`docker stack deploy`). Swarm forbids fixing a container name and mangles it per task/replica (`{stack}_{service}.{slot}.{task-id}`), so exact-name matching never works for a Swarm-deployed service — `services` matches Docker's own stable Swarm **service** name (`{stack_name}_{name}`) instead, via the Docker Engine Services API rather than the container-listing endpoint.

```yaml
# Standalone / docker-compose container
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
# Docker Swarm service
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

| Field | Description |
|---|---|
| `environment_id` | Portainer's **endpoint ID** (not free-form): the number Portainer assigns to each registered environment. It's obtained in the Portainer UI (**Environments**, environment column) or by querying `GET {portainer_url}/api/endpoints` with the service token (`X-API-Key` header) — this is how `environment_id` was resolved for each cluster node when the catalog's 25 new services were onboarded. The runner uses it literally in the path `api/endpoints/{environment_id}/docker/containers/...` or `.../docker/services/...` (`runner/src/capataz_runner/executor.py`), so an incorrect value doesn't fail YAML validation — it fails at runtime against Portainer. |
| `stack_name` | With `containers`, it's **purely informational** — persisted and shown on the card ("Stack: homelab-retaco"), but not used to resolve or filter containers (only `containers[].name` is). With `services`, it **is used**: each declared service name is resolved as `{stack_name}_{name}` against Docker's Swarm service listing, exactly matching what `docker stack deploy -c file.yml {stack_name}` names things — an incorrect `stack_name` here means no service ever matches. |
| `aggregation` | `all_required` (default) or `any_healthy`. Determines how observed containers/services are combined for the aggregate status (`aggregate_status` in `application/policies/status.py`): with `all_required`, the service is `healthy` only if **all** entries with `required: true` are running (and healthy — for a Swarm service, "healthy" means its running task count matches its desired task count); with `any_healthy`, it's enough for **any one** to be running and healthy. In both cases, if the declared external healthcheck (`health:`) fails, the service drops to `degraded`/`down` as applicable. |
| `containers[].name` | The container's **exact** name in Docker (`docker ps --format '{{.Names}}'` on the node, or the name visible in Portainer). It's the only piece of data the runner and `StatusService` use to locate the container within the declared `environment_id` — a client-supplied container ID is never accepted anywhere in the flow. |
| `containers[].required` / `containers[].critical` | Defaults `true`/`false`. `required: false` means the container is observed and reported but doesn't count toward `down` under `aggregation: all_required`. `critical: true` marks the service `down` unconditionally whenever that specific container isn't running, regardless of `aggregation` or the other containers' state. |
| `services[].name` | The Swarm service's short name, **without** the stack prefix (e.g. `authentik-server`, not `homelab-swarm_authentik-server`) — the full name is derived from `stack_name` + this field. |
| `services[].replicas` | 0–50, defaults to `1`. The replica count a `start` action scales the service back up to, and what a healthy/fully-scaled read compares `RunningTasks` against. If the service is ever rescaled outside Capataz (`docker service scale`), the next `start`/`restart` from Capataz will re-scale it back down/up to this declared value — keep it in sync with the real desired capacity. |
| `services[].required` / `services[].critical` | Same semantics as the `containers[]` equivalents above. |

## `health`

```yaml
health:
  type: http
  url: https://openwebui.404labo.net/health
  expected_status: 200
  timeout_seconds: 5
```

| Field | Description |
|---|---|
| `type` | `http` or `tcp` in the schema (`Literal["http", "tcp"]`), but **only `http` is implemented**: `HttpHealthProber` (`adapters/outbound/health.py`) always makes an HTTP GET request, whatever the value of `type`. Declaring `type: tcp` doesn't raise a validation error nor does a real TCP connect — today it behaves exactly like `http`. Don't use it until this item is implemented. |
| `url` | Must be `http`/`https` with a hostname. Subject to real SSRF defense (`validate_health_url`): it's rejected if the host is an IP (unless it also ends in an allowed suffix), if it resolves to loopback/link-local/private range, or if the hostname doesn't end in one of the `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` suffixes (defaults to `.404labo.net`; see `core/settings.py`). This is the **only** catalog URL the API ever requests itself; `service_url`/`documentation_url` don't go through this because they're never requested from the server. |
| `expected_status` | HTTP code considered "healthy" (100–599, defaults to `200`). |
| `timeout_seconds` | 1–60, defaults to `5`. |

## `grafana` / `loki`

Both are **completely free-form** objects (`dict[str, Any]`, with no shape or allowed-key validation despite what the name suggests) that `resolve_links` (`application/policies/links.py`) uses to build read-only links to external tools — the Grafana/Loki server is never called from the API, so these don't go through the SSRF defense either.

```yaml
grafana:
  dashboard_uid: homelab-generic/generic-service
  variables:
    var-service: ollama-service
    kiosk: tv
loki:
  query: '{compose_service="ollama"}'
```

- `grafana.dashboard_uid`: the panel's UID in your Grafana (visible in the dashboard URL: `.../d/<uid>/...`). It's concatenated literally into `{grafana.base_url or grafana_url}/d/{dashboard_uid}`; `/` is left unescaped, so a folder-qualified UID like `homelab-generic/generic-service` works as-is.
- `grafana.variables`: key/value pairs used verbatim as URL query parameters — nothing is auto-prefixed, so give the **full** parameter name Grafana expects, e.g. `var-service` for a template variable named `service`, or a non-variable modifier like `kiosk: tv`. A parameter that doesn't match a template variable defined in that dashboard is simply ignored by Grafana.
- `grafana.base_url`: optional; overrides the system-wide `CAPATAZ_GRAFANA_URL` for this service only, for a service whose dashboards live on a different Grafana instance.
- `grafana.dashboard_url`: optional; the complete dashboard path (or a full `http(s)://` URL) to use as the Grafana link, **ignoring `dashboard_uid` and `variables` entirely** when set. A relative value (not starting with `http://`/`https://`) is appended to `grafana.base_url` or the system `CAPATAZ_GRAFANA_URL`.
- `loki.query`: a raw LogQL expression placed as the `left` parameter of `{loki_url}/explore?...`. No escaping beyond standard `urlencode`.

`CAPATAZ_GRAFANA_URL`/`CAPATAZ_LOKI_URL`/`CAPATAZ_PORTAINER_URL` (environment variables, see `core/settings.py`) must be configured for these links to be generated unless `grafana.base_url` (or an absolute `grafana.dashboard_url`) supplies its own; if no base URL is available from any of these sources, the link simply doesn't appear.

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

An optional list of metrics to show on this service's card and detail page. Each entry:

| Field | Description |
|---|---|
| `label` | Free text shown above the value on the card (1–100 chars). Not localized — it's whatever the admin types. |
| `type` | `Literal["prometheus"]` today — the only implemented provider. The schema (`MetricDefinitionCatalog`) and the `MetricsProviderPort` this maps to are provider-agnostic, so a future adapter (Netdata, CloudWatch, ...) adds another literal value here without changing this field's shape. |
| `query` | The **complete** PromQL text (1–2000 chars), run verbatim against `{CAPATAZ_PROMETHEUS_URL}/api/v1/query`. If Prometheus returns more than one series (the query wasn't fully aggregated to a single value), the series are summed. |

**Trust boundary:** unlike `health.url`'s SSRF-validated hostname or the runner's allow-listed Ansible `extra_vars`, `query` has no shape/content validation beyond a length cap — it is trusted verbatim. This is intentional and safe: `metrics` is written by whoever can edit the catalog (`capataz-admin` only, enforced by the same RBAC that gates every other catalog mutation), never derived from an execution request or any other end-user input at request time. Treat a catalog `query` the same as you would a `health.url` or an Ansible playbook path — operator-authored config, not something to accept from an untrusted source. See docs/06-security.md.

Metrics are queried by the API's `StatusService` alongside the existing Portainer/health checks — see [infra/prometheus/README.md](../infra/prometheus/README.md) for how the querying and caching works. A service with no `metrics` block simply shows no metrics row.

## `actions`

```yaml
actions:
  - key: restart
    label: Restart
    description: Restarts the container without losing persisted data.
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

| Field | Description |
|---|---|
| `key` | Unique slug **per service** (`^[a-z0-9][a-z0-9-]*$`), identifies the action in the execution URL and in the upsert. |
| `label` | Button text/tooltip on the card and on the service/execution pages. |
| `description` | It's persisted and exposed via the API, but **is not shown anywhere in the current frontend** (no tooltip, no detail view) — it documents the action only for whoever reads/exports the YAML. |
| `icon` | Same as the service `icon`: a Material Icons ligature; same risk if the name doesn't exist in the bundled font. |
| `action_type` | `portainer`, `ansible`, `http`, `ssh`, or `rsync`. The schema accepts all five, but **only `portainer` and `ansible` actually execute**: `resolve_action` (`application/policies/actions.py`) explicitly rejects `http`/`ssh`/`rsync` at runtime with `"Action type is modelled but not executable in V1"` — they can be declared and seen in the catalog, but any attempt to execute them always fails. See `docs/12-roadmap.md` ("Connectors" item) for the proposal to give them real connectivity. |
| `risk_level` | `read`, `operate`, or `critical`. See the role table below — **it's not just informational**, it determines the minimum role that can execute the action. |
| `requires_confirmation` | Boolean, defaults to `false`. **Declared but not implemented.** It can be set from YAML or from the "New action" form in `CatalogPage.vue`, it's persisted, and it's returned by the API — but no point in the execution flow reads it: neither `authorize_action` (`application/policies/rbac.py`, which only looks at `risk_level`), nor the frontend (`ServiceCard.vue`/`ServiceDetailPage.vue` decide whether to show the confirmation dialog by literally checking `action.risk_level === 'critical'`, not this field). Today, setting `requires_confirmation: true` on an `operate` action has no observable effect. What it should do: require explicit confirmation (and optionally a reason) on execution, independently of `risk_level`, so that an `operate` action can be marked as "requires confirmation" without having to bump it to `critical` (e.g. a `restart` that affects other services). |
| `enabled` | Boolean, defaults to `true`. If `false`, `resolve_action` rejects any execution attempt (`"Action is not enabled for this service"`) — this one is actually implemented and active. |
| `unattended` | Boolean, defaults to `false`. A UI preference, not a security one: if `true`, the frontend fires the action and stays on the originating screen refreshing the service status, instead of navigating to the execution detail. Meant for quick, single-step actions (`start`/`stop`/`restart`); leave it `false` for actions whose output is worth inspecting (`logs`, Ansible actions). |
| `config` | Validated according to `action_type`, see below. It can never contain the `command` key (always rejected, regardless of type). |
| `allowed_parameters_schema` | A simplified JSON-Schema-like object: `{"properties": {"<param>": {"enum": [...]}}}`. If defined, it **is** actually enforced in `resolve_action`: any parameter sent at execution time (`POST .../execute`, `params` field) that isn't in `properties` is rejected, and if a parameter's definition carries `enum`, the sent value must be in that list. The keys `command`, `container_id`, `url`, and `playbook_path` are additionally always forbidden as execution parameters, regardless of this schema. If omitted (`{}`, the default value), the action accepts no parameters at execution time. |

### `config` for `action_type: portainer`

Only exactly this shape is accepted — any other key, or a value outside these lists, is rejected both in catalog validation and (redundantly, belt and suspenders) in the runner:

```yaml
config:
  operation: restart              # start | stop | restart | logs
  target: selected_containers     # selected_containers | selected_services
```

`target` must be `selected_containers` or `selected_services`, and **must match the selector kind declared under the service's own `portainer` block** (`selected_services` when it declares `services`, `selected_containers` when it declares `containers` — a mismatch is rejected at catalog-validation time by `ServiceCatalog`'s own validator). A specific container/service ID is never accepted from the client/catalog — the runner resolves the actual target from `service.container_selectors` (the `portainer.containers`/`portainer.services` block), never from `config`.

For `selected_services`, the four operations map onto the Docker Swarm Services API rather than the container start/stop/restart/logs verbs (Swarm services don't have those): `restart` is a **force update** (`docker service update --force` equivalent — redeploys every task, same image/spec), `logs` aggregates logs across all of the service's tasks, and `stop`/`start` **scale replicas to 0 / back up to the declared `services[].replicas`** — they don't remove or recreate the service. Because `start` always re-asserts the declared `replicas` value, a service rescaled outside Capataz will be reset to that value by the next `start`/`restart` from Capataz.

### `config` for `action_type: ansible`

```yaml
config:
  playbook: playbooks/backup_service.yml
  inventory: inventories/homelab.yml
  limit: node-ai-01
  extra_vars:
    service: open-webui
  timeout_seconds: 600
```

The whole block is subject to a fixed allow-list in the **runner** (`runner/src/capataz_runner/actions.py`), not in the YAML catalog — the catalog only checks the path prefix (`playbooks/`/`inventories/`, no `..`); the actual, closed list of accepted values is:

| Field | Current allow-list | Notes |
|---|---|---|
| `playbook` | `playbooks/restart_service.yml`, `playbooks/backup_service.yml`, `playbooks/check_connectivity.yml` (`ALLOWED_PLAYBOOKS`) | Must be exactly one of these three — not any path under `playbooks/`. Adding a new playbook requires adding it to `runner/playbooks/` **and** to this constant in the code. |
| `inventory` | `inventories/homelab.yml`, `inventories/local.yml` (`ALLOWED_INVENTORIES`) | Same, a closed value. |
| `limit` | Any safe slug (`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$`) that also exists as a host/group in the chosen inventory. `inventories/homelab.yml` today only defines `node-ai-01` and `node-gpu-01` as placeholders — not the cluster's real nodes (`retaco`, `ryzen`, `pi-*`), which are indeed onboarded in `catalog/services.example.yaml` via Portainer. Services whose actions are of type `portainer` are unaffected; ones that need an Ansible action in the future will first need to add their real host to this inventory. |
| `extra_vars` | Only the keys `service`, `backup_label` (`ALLOWED_EXTRA_VARS`); each value must satisfy the same safe slug as `limit`. | Any other key is rejected. |
| `timeout_seconds` | Integer between 1 and 900 (defaults to 300 if omitted). | |

## Role Table by `risk_level`

`risk_level` is not descriptive: it's what the API uses in `authorize_action` (`application/policies/rbac.py`) to decide whether the authenticated user can execute that specific action.

| `risk_level` | Minimum role to **execute** | Additional requirement |
|---|---|---|
| `read` | `capataz-operator` | None. **Note:** an action being read-only (e.g. `logs`) doesn't open it up to `capataz-viewer` — any execution, including `read`-risk ones, requires at least the operator role. A viewer can only *see* already-existing services, status, executions, and audit records, never trigger an action. |
| `operate` | `capataz-operator` | None. |
| `critical` | `capataz-admin` | The execution request must include `confirmation: true` and a non-empty `reason`, or the API rejects it (403) — this is the only real confirmation that exists in the system today, and it's unconditional for `critical` (it doesn't depend on `requires_confirmation`, see above). |

## Complete Example

`catalog/services.example.yaml` contains the homelab's real catalog (27 services as of this document) and serves as a living reference — more reliable than any isolated snippet on this page, because it's validated and imported against the real API.

## Prohibitions

Do not include passwords, tokens, keys, Vault values, DSNs, free-form commands, `shell`, an unversioned playbook, an external inventory, a client container ID, or an execution URL. This will be rejected by validation; the YAML being syntactically correct does not make it allowed.

## Import, Dry-run, and Export

- Optional startup: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. If set but the file doesn't exist or doesn't validate, startup/readiness fails explicitly. If it validates, the upsert is transactional and idempotent.
- API: `POST /api/v1/catalog/import` accepts `{"yaml":"...","dry_run":true}` to validate without writing, and `dry_run=false` to persist. The interface should show line/field errors.
- Operational CLI: `make seed-catalog` imports the example via the API CLI.
- Export: `GET /api/v1/catalog/export` or `make export-catalog > catalog/export.yaml`. The result strips secrets, transient results, and execution data.

An import updates the service whose `id` matches and its actions by logical identifier; it does not implicitly delete data that isn't present, except via an explicit, audited option that may be added in the future (see `docs/12-roadmap.md`, the item about `upsert_catalog`).

## Common Errors

- **Duplicate ID / duplicate key**: use a globally unique `id` and a `key` unique per service.
- **`health` URL rejected**: the host/scheme doesn't pass the SSRF policy or isn't in the allow-listed suffix (`CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES`). `service_url`/`documentation_url` are never rejected for this reason because they're never requested from the server.
- **Invalid `ansible` action**: playbook/inventory outside the runner's `ALLOWED_PLAYBOOKS`/`ALLOWED_INVENTORIES` constants (not an allow-list in the YAML), `limit` with disallowed characters, `extra_vars` with a key outside `ALLOWED_EXTRA_VARS`, or `timeout_seconds` outside 1–900.
- **`http`/`ssh`/`rsync` action**: it's saved without error, but any execution will always fail with `"Action type is modelled but not executable in V1"` — it's not a badly written catalog, it's a known limitation (see `docs/12-roadmap.md`).
- **Icon that doesn't show or overflows the card**: the name doesn't exist in the bundled Material Icons font — confirm it at [fonts.google.com/icons](https://fonts.google.com/icons?icon.set=Material+Icons) within the **"Material Icons"** set (not Symbols/Outlined/Round).
- **Missing startup catalog**: fix the mounted path; don't disable the failure without understanding why.
