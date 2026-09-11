# ADR 008: Connectors and Encrypted Resources (Catalog v2)

*Language: **English** · [Español](008-connectors-and-resources.es.md)*

- **Status:** Accepted
- **Date:** 2026-09-11
- **Partially supersedes:** [ADR 003](003-secrets-and-credentials.en.md) (action credentials only)

## Context

Until catalog v1, every integration had exactly **one** global identity: the Portainer, Grafana,
Loki and Prometheus URLs were `CAPATAZ_*_URL` environment variables, and the Portainer token, the
runner's SSH key, its `known_hosts` and the Ansible Vault password were fixed Docker secrets. Each
service embedded its own Portainer/health/Grafana/Loki/metrics configuration inline. As a result:

- Two Portainer instances, two SSH keys or one host with different credentials could not coexist.
- Adding a field or an integration type meant touching ~8 layers (schema, DTO, ORM, repository,
  policies, runner, frontend, docs) — roadmap item 11.
- Credentials could only be changed by an operator with access to the hosts (a new Docker secret
  and a redeploy), never from the application.

## Decision

A three-layer model, all declared in **one catalog file** (`version: 2`) and also editable through
the API/UI:

1. **Resources** — files and secrets (`secret`, `ssh_private_key`, `known_hosts`, `file`) stored
   **encrypted in PostgreSQL**. The API never returns their content, only metadata (type, size,
   short fingerprint, provenance, version).
2. **Connectors** — typed connection plugins (`portainer`, `prometheus`, `grafana`, `loki`, `http`,
   `ansible`, `ssh`). Each type is a Pydantic config model (a discriminated union on `type`) that
   declares its **capabilities** (`status`, `actions`, `metrics`, `health`, `dashboards`, `logs`)
   and which of its fields reference a resource, and of which type.
3. **Services** — a JSON `spec` (runtime, observability, tags...) that references connectors by
   capability; every action references a connector with the `actions` capability, and its `config`
   is validated with the action model of that connector's type.

Key rules:

- **Resource sources in the YAML.** `{file: name}` is read from `CAPATAZ_RESOURCES_DIR` (default
  `/run/capataz-resources`), confined by `realpath` (no `..`, no escaping symlinks) and capped at
  64 KiB — otherwise an admin could import `/run/secrets/database_url` as a resource.
  `{env: VAR, encoding: plain|base64}` reads an environment variable of the API process.
  `{base64: ...}` is an inline literal, for development/tests only: the import returns a warning,
  and it is **refused when `CAPATAZ_ENV=production`** unless `CAPATAZ_ALLOW_INLINE_RESOURCES=true`.
  Without `source`, the resource must already exist in the database (uploaded from the UI). An
  export never includes content.
- **Encryption.** `cryptography`'s MultiFernet with the `resources_master_key` Docker secret: one
  key per line, the first one encrypts and all of them decrypt, which allows rotation. A keyed
  HMAC-SHA256 fingerprint (not a plain SHA, which would allow guessing low-entropy tokens) detects
  unchanged content on re-import.
- **Who decrypts.** The API, only for what it uses itself (Portainer/Prometheus tokens for status
  and metrics). The runner, for action credentials, with its own decrypt-only copy of the cipher
  (both suites test a shared vector). **The queue still carries only `execution_id`**: the runner
  re-reads action, connector and resources from PostgreSQL, decrypts in memory and writes key
  material only to a per-execution `0700` temporary directory (`0600` files) removed afterwards.
- **SSH with an allow-list.** An `ssh` action carries `command_id` + validated `params`, never text:
  the commands live in the versioned `runner/ssh_commands.yml` (argv with whole-element
  `{param}` placeholders, `pattern`/`enum` per parameter, timeout per command). The remote command
  is shell-quoted element by element; `BatchMode=yes`, `StrictHostKeyChecking=yes` and a pinned
  `known_hosts`. The `command` key is still forbidden everywhere.
- **SSRF.** `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` is the global ceiling for every outbound URL:
  health checks, connector URLs and SSH hosts. An `http` connector's `allowed_host_suffixes` can
  only narrow it, never widen it. Portainer URLs must be `https` (the token travels on every
  request).
- **Persistence.** `services.spec` (JSONB) plus denormalized `name`/`group_name`/`environment`
  columns for SQL filters; new `resources` and `connectors` tables; `action_definitions.connector_id`
  is a foreign key with `ON DELETE RESTRICT`. Migration `0009` converts v1 rows, creating placeholder
  connectors from the old `CAPATAZ_*_URL` variables; it is irreversible (`pg_dump` first).
  `scripts/convert_catalog_v1_to_v2.py` converts a v1 YAML file.

## Consequences

- Several Portainer instances, SSH keys or Prometheus servers can coexist, and credentials can be
  rotated from the UI without redeploying anything.
- A new integration type is one config model plus an adapter; services, the catalog and the UI pick
  it up through its capabilities.
- `resources_master_key` becomes the most critical secret of the deployment: losing it means
  re-uploading every resource; leaking it together with a database dump exposes all of them. It is
  mounted only on `api` and `runner`.
- A catalog admin can make a connector *use* any resource, but can never read one back, and a
  connector can only reach hosts inside the global suffix ceiling — a resource cannot be
  exfiltrated to an arbitrary destination.
- Migration `0009` is one-way; rolling back means restoring the dump and the previous images.
- The frontend mirrors the runner's allow-lists (playbooks, inventories, SSH command ids) as
  constants, as it already did for playbooks; the runner stays the source of truth.

## Alternatives Considered

- **One Docker secret per credential, referenced by name from the connector** (the original
  roadmap proposal): keeps secrets out of the database, but adding or rotating a credential still
  needs host access and a redeploy — exactly the limitation being removed.
- **External secret manager (Vault, AWS Secrets Manager):** better for larger deployments, but a
  heavy new dependency for a homelab; the `ResourceCipher` port leaves room for it later.
- **Free-text SSH commands:** rejected — it would reintroduce the arbitrary remote execution the
  project exists to avoid.
- **Plaintext resources in the database:** rejected; any dump or backup would leak every credential.

## Relation to ADR 003

ADR 003 still governs `database_url`, `redis_url`, `postgres_password`, `redis_password`,
`cognito_client_secret` and the new `resources_master_key`. The `portainer_token`,
`prometheus_token`, `runner_ssh_private_key`, `runner_known_hosts` and `ansible_vault_password`
Docker secrets are replaced by resources referenced from connectors.
