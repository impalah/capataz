# Security

*Language: **English** · [Español](06-security.es.md)*

## Summary Threat Model

Capataz mediates between an authenticated user and powerful operational capabilities. The main risks are: privilege escalation via broken RBAC, arbitrary remote execution, secret leakage, SSRF abuse via healthchecks, compromise of the runner/Docker host, queue manipulation, and loss of traceability. The response is deny-by-default: verifiable identity, least privilege, declared configurations, and auditing.

## Secrets and Minimal Exposure

| Secret | Consumers | Purpose |
|---|---|---|
| `database_url` | api, runner | Full SQLAlchemy DSN (password included); treated as a single secret, not assembled from loose parts. |
| `redis_url` | api, runner | Full Redis URL (password included); broker/result backend and cache. |
| `postgres_password` | postgres | Only the container's own initialization. |
| `redis_password` | redis | Only the container's own `--requirepass`. |
| `cognito_client_secret` | api | Cognito integration. |
| `resources_master_key` | api, runner | Fernet key(s) that encrypt the catalog resources; the first line encrypts, every line decrypts (rotation). |

All of these are injected as `/run/secrets/*` files, read-only and only to the consumer that needs them. They are not in Git, `.env`, YAML, parameters, logs, exceptions, snapshots, or responses. Create files with `umask 077`, apply `chmod 600`, rotate on suspicion, and restart consumers. Sanitize logs against token, private key, bearer, password, and Vault patterns before persisting `ExecutionEvent`.

## Catalog Resources (Encrypted Integration Credentials)

Portainer/Prometheus tokens, SSH private keys, `known_hosts` and Ansible Vault passwords are not Docker secrets any more: they are catalog **resources** ([ADR 008](adr/008-connectors-and-resources.en.md)), referenced by connectors.

- **At rest:** encrypted with MultiFernet and `resources_master_key` before being stored in PostgreSQL; a database dump alone doesn't reveal them. A keyed HMAC-SHA256 fingerprint (never a plain hash, which would allow guessing low-entropy tokens) is what detects unchanged content.
- **Never returned:** the API exposes metadata only (type, size, 12-character fingerprint, provenance, version); audit records never include content; the catalog export never includes it.
- **Loading sources:** `{file: name}` is confined to `CAPATAZ_RESOURCES_DIR` by `realpath` (no `..`, no escaping symlinks, 64 KiB maximum), so an admin can't import `/run/secrets/database_url` as a resource — keep that directory (`./resources` in Compose) separate from `./secrets`. `{env: VAR}` reads the API's environment. `{base64: ...}` inline in the YAML is development-only: it produces a warning and is refused with `CAPATAZ_ENV=production` unless `CAPATAZ_ALLOW_INLINE_RESOURCES=true`.
- **Use:** the API decrypts only what it uses itself (Portainer/Prometheus tokens for status and metrics). The runner decrypts an action's credentials right before executing it, keeps them in memory, adds every decrypted value to its redaction list, and writes key material only to a per-execution `0700` temporary directory (`0600` files) deleted when the execution ends — including on failure or timeout.
- **Boundary:** an admin can make a connector *use* any resource but can never read one back, and connectors only reach hosts inside the global suffix allow-list (see SSRF below), so a resource can't be pointed at an arbitrary destination. `resources_master_key` is therefore the deployment's most sensitive secret: losing it means re-uploading every resource, and leaking it together with a database dump exposes all of them.

## RBAC and Confirmation

`viewer < operator < admin`. Viewer only reads; operator executes `read` and `operate` actions; admin adds CRUD, catalog, audit, and `critical`. The backend decides using the persisted definition, not information from the browser. For `critical`, explicit confirmation and a mandatory reason are required. Every change records actor, action, resource, source, result, and IP/request ID when available.

## Allow-list Policy

A service definition selects container/Swarm service names in its `runtime`, not client-supplied IDs. Portainer actions restrict `operation` to `start`, `stop`, `restart`, or `logs`; Ansible restricts playbook, limit, extra-vars, and timeout to versioned/validated values, and its inventory (from the connector) to the runner's allow-list; SSH actions only select a `command_id` from the versioned `runner/ssh_commands.yml`, whose argv placeholders take whole elements and whose parameters must match a `pattern`/`enum` — the remote command is also shell-quoted element by element, since the remote side always runs it through the login shell. There is no `shell=True`, `command`, external path, execution URL, or interpolation of user arguments. The worker reloads the definition (action, connector, resources) from the database and the queue only carries a UUID.

**Known residual risk — Portainer logs (`logs` action):** `sanitize_text` redacts *known* secret patterns (bearer/`password:`/x-api-key/vault) before persisting `docker logs` output as an `ExecutionEvent`, but that output comes from third-party containers Capataz doesn't control — if a service logs a secret in a format the regex doesn't recognize (e.g. `DB_PASS=hunter2`), it would end up persisted almost unredacted in Capataz's audit table/SSE. There is no additional mitigation today; if this is a concern for a specific service, restrict that service's `logs` action to a higher `risk_level` in the catalog, or avoid declaring the `logs` action for services known to log sensitive data in plain text.

## Catalog Metrics (PromQL Trust Boundary)

`metrics[].query` (docs/05-yaml-catalog.md) is the one catalog field that carries free-form text run against an external system — full PromQL, not validated for shape or content beyond a length cap, unlike every other integration point above. This is deliberate, not an exception to the allow-list policy: the query is authored by whoever can edit the catalog (`capataz-admin` only, gated by the same RBAC as every other catalog mutation), never derived from an execution request, a lower-privileged role, or any other input received at request time. It sits at the same trust level as `health.url` or an Ansible playbook path — operator-declared config, not client input — and PromQL itself is read-only against Prometheus (no mutation capability), bounded by `CAPATAZ_HTTP_TIMEOUT_SECONDS`, and never templated or string-concatenated with anything else before being sent. If this Prometheus is ever shared with a lower-trust audience, treat catalog-edit access (`capataz-admin`) as the boundary that protects it — the same way you'd treat Ansible playbook authorship today.

## Docker Socket

Mounting `/var/run/docker.sock` normally amounts to granting very broad control over the Docker host and, by extension, possible root on the host. For that reason the API does not mount the socket, and V1 integrates with Portainer using a minimal token. If V2 needs to create jobs, a Docker socket proxy with allow-listed endpoints and mutual authentication, or Kubernetes Jobs, will be evaluated; see the ephemeral runner design. Don't turn the socket into a shortcut for debugging.

## SSH, sudo, and Ansible

The key belongs to an automation account, with no human login or reuse, with per-host access restricted in `authorized_keys`. `known_hosts` is pinned by fingerprint; don't disable key checking (the runner always passes `StrictHostKeyChecking=yes`, and `BatchMode=yes` for `ssh` connectors). Grant `sudo` per essential command/task, not `NOPASSWD: ALL`. Playbooks, inventories and `ssh_commands.yml` are versioned and packaged read-only. Vault is used for automation secrets, but it does not replace Docker Secrets for control-plane credentials. For an `ssh` connector's key, also pin what it may run with a forced `command=`/`restrict` in the target's `authorized_keys` where practical — defence in depth on top of the allow-list.

**Manual key provisioning (out of repo scope):** Capataz never generates or distributes these key pairs — it only consumes the private half from an `ssh_private_key` resource referenced by an `ansible` or `ssh` connector (`private_key` field). Provisioning and rotation are a manual operator procedure, run outside the repo, whenever a new homelab node is added or the key rotates:

1. Generate an ed25519 key pair on a trusted admin workstation — never on the runner host or in CI:
   ```
   ssh-keygen -t ed25519 -C "capataz-automation" -f ./runner_ssh_private_key -N ""
   ```
   No passphrase (`-N ""`): the runner uses the key unattended, so the resource encryption (and the `0600` per-execution file it materializes) is the protection layer, not a passphrase prompt.
2. Upload the private half as an `ssh_private_key` resource — **Catalog → Resources → New resource** in the UI, or a catalog resource with `source: {file: runner_ssh_private_key}` placed under `CAPATAZ_RESOURCES_DIR` (`./resources/`, gitignored) — and reference it from the connector's `private_key`.
3. Append the public half (`runner_ssh_private_key.pub`) to `~capataz_automation/.ssh/authorized_keys` on every node listed in `runner/inventories/*.yml` (the account is `ansible_user: capataz_automation`), ideally constrained with a `from="<homelab CIDR>"` prefix since this account should only ever be reached from the runner host.
4. Pin host keys: from the runner host (or an equivalent vantage point on the homelab network), run `ssh-keyscan` against every inventory host, verify each fingerprint out-of-band (console, IPMI, or another already-trusted channel — not the same network path you're trying to verify), and store the result as a `known_hosts` resource referenced by the connector's `known_hosts`.
5. Securely wipe the local copy of the private key material from the admin workstation (and from `./resources/`, if it was imported from a file) once it's stored as a resource (e.g. `shred -u`) — no standing plaintext copy should remain.
6. Rotate by repeating steps 1-5 with a new key pair, replacing the resource's content (**Replace content**, no restart needed), verifying connectivity, and only then removing the old public key from every node's `authorized_keys`.

## SSRF and Health Probes

On import/CRUD only `http` and `https` are allowed, the destination is resolved and validated before connecting, loopback, link-local, RFC1918/cloud metadata are denied except via an explicit homelab allow-list, redirects to new destinations are prevented, and short timeouts are enforced. The refresh endpoint receives a service ID, never a URL. Responses must not reflect sensitive remote bodies.

The same rules cover every outbound destination a catalog can declare, not just health checks: connector URLs (Portainer, Prometheus, Grafana, Loki) and SSH hosts are validated against `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (`application/policies/outbound_urls.py`), which is the global ceiling — an `http` connector's `allowed_host_suffixes` can only narrow it, never widen it. Portainer URLs must be `https`, because the token travels on every request.

**Known residual risk — DNS rebinding:** `validate_outbound_url` validates the hostname string against the suffix allow-list, but doesn't resolve or pin the IP that `httpx` ends up connecting to — a hostname allowed by suffix whose internal DNS resolves (at request time) to an unexpected private/loopback/metadata IP would pass validation. This is accepted as low risk given the homelab's closed trust model (the DNS resolving `.404labo.net` is owned by the operator), but it is a real gap against the literal SSRF requirement if that trust boundary ever changes.

## Operational Hardening

The `internal` network does not expose databases/broker; containers use a read-only filesystem where possible, temporary tmpfs, `cap_drop: ALL`, `no-new-privileges`, and CPU/memory limits. Keep images pinned, updated, and scanned with Trivy; use Dependabot and gitleaks. Periodically review Portainer tokens, Cognito groups, inventories, audit logs, and backup restores.

**Design note — no internal TLS:** `postgresql+asyncpg://`/`redis://` (API and runner) do not use TLS between services; this is accepted today because all communication happens within the unexposed Docker `internal` network. If the deployment model were to change (e.g. Postgres/Redis on a separate host without a shared trust network), parameterizable `sslmode`/`rediss://` support would need to be added before exposing those connections outside an isolated network.
