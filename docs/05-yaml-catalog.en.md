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

| Field | Description |
|---|---|
| `environment_id` | Portainer's **endpoint ID** (not free-form): the number Portainer assigns to each registered environment. It's obtained in the Portainer UI (**Environments**, environment column) or by querying `GET {portainer_url}/api/endpoints` with the service token (`X-API-Key` header) — this is how `environment_id` was resolved for each cluster node when the catalog's 25 new services were onboarded. The runner uses it literally in the path `api/endpoints/{environment_id}/docker/containers/...` (`runner/src/capataz_runner/executor.py`), so an incorrect value doesn't fail YAML validation — it fails at runtime against Portainer. |
| `stack_name` | **Purely informational.** It's persisted and shown on the card ("Stack: homelab-retaco") but is not used to resolve or filter containers — the actual container matching only uses `containers[].name` (see below). It should match the stack's real `com.docker.compose.project` label in Docker so the displayed information is accurate, but nothing validates this. |
| `aggregation` | `all_required` (default) or `any_healthy`. Determines how observed containers are combined for the aggregate status (`aggregate_status` in `application/policies/status.py`): with `all_required`, the service is `healthy` only if **all** containers with `required: true` are running (and healthy if Portainer reports a healthcheck); with `any_healthy`, it's enough for **any one** of the observed containers to be running and healthy. In both cases, if the declared external healthcheck (`health:`) fails, the service drops to `degraded`/`down` as applicable. |
| `containers[].name` | The container's **exact** name in Docker (`docker ps --format '{{.Names}}'` on the node, or the name visible in Portainer). It's the only piece of data the runner and `StatusService` use to locate the container within the declared `environment_id` — a client-supplied container ID is never accepted anywhere in the flow. |
| `containers[].required` | Defaults to `true`. If `false`, the container is observed and reported but doesn't count toward deciding whether the service is `down` when `aggregation: all_required`. |
| `containers[].critical` | Defaults to `false`. If `true` and that specific container is not running, the service is marked `down` **unconditionally**, regardless of the `aggregation` value or the state of the other containers. |

## `health`

```yaml
health:
  type: http
  url: https://openwebui.home.arpa/health
  expected_status: 200
  timeout_seconds: 5
```

| Field | Description |
|---|---|
| `type` | `http` or `tcp` in the schema (`Literal["http", "tcp"]`), but **only `http` is implemented**: `HttpHealthProber` (`adapters/outbound/health.py`) always makes an HTTP GET request, whatever the value of `type`. Declaring `type: tcp` doesn't raise a validation error nor does a real TCP connect — today it behaves exactly like `http`. Don't use it until this item is implemented. |
| `url` | Must be `http`/`https` with a hostname. Subject to real SSRF defense (`validate_health_url`): it's rejected if the host is an IP (unless it also ends in an allowed suffix), if it resolves to loopback/link-local/private range, or if the hostname doesn't end in one of the `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` suffixes (defaults to `.home.arpa`; see `core/settings.py`). This is the **only** catalog URL the API ever requests itself; `service_url`/`documentation_url` don't go through this because they're never requested from the server. |
| `expected_status` | HTTP code considered "healthy" (100–599, defaults to `200`). |
| `timeout_seconds` | 1–60, defaults to `5`. |

## `grafana` / `loki`

Both are **completely free-form** objects (`dict[str, Any]`, with no shape or allowed-key validation despite what the name suggests) that `resolve_links` (`application/policies/links.py`) uses to build read-only links to external tools — the Grafana/Loki server is never called from the API, so these don't go through the SSRF defense either.

```yaml
grafana:
  dashboard_uid: containers-overview
  variables:
    service: ollama-service
loki:
  query: '{compose_service="ollama"}'
```

- `grafana.dashboard_uid`: the panel's UID in your Grafana (visible in the dashboard URL: `.../d/<uid>/...`). It's concatenated literally into `{grafana_url}/d/{dashboard_uid}`.
- `grafana.variables`: key/value pairs translated into `var-<key>=<value>` URL parameters — they must match the template variable names defined in that specific Grafana dashboard, otherwise Grafana simply ignores them.
- `loki.query`: a raw LogQL expression placed as the `left` parameter of `{loki_url}/explore?...`. No escaping beyond standard `urlencode`.

`CAPATAZ_GRAFANA_URL`/`CAPATAZ_LOKI_URL`/`CAPATAZ_PORTAINER_URL` (environment variables, see `core/settings.py`) must be configured for these links to be generated; if the corresponding base URL is missing, the link simply doesn't appear.

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
  operation: restart   # start | stop | restart | logs
  target: selected_containers   # only accepted value
```

`target` must always be the literal `selected_containers`: a specific container ID is never accepted from the client/catalog — the runner resolves the actual containers from `service.container_selectors` (the `portainer.containers` block above), never from `config`.

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
