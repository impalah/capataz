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
| `portainer_token` | api, runner | Read access / allow-listed platform actions. |
| `cognito_client_secret` | api | Cognito integration. |
| `runner_ssh_private_key` | runner | Automation technical account. |
| `runner_known_hosts` | runner | SSH host verification. |
| `ansible_vault_password` | runner | Ansible Vault secret. |

All of these are injected as `/run/secrets/*` files, read-only and only to the consumer that needs them. They are not in Git, `.env`, YAML, parameters, logs, exceptions, snapshots, or responses. Create files with `umask 077`, apply `chmod 600`, rotate on suspicion, and restart consumers. Sanitize logs against token, private key, bearer, password, and Vault patterns before persisting `ExecutionEvent`.

## RBAC and Confirmation

`viewer < operator < admin`. Viewer only reads; operator executes `read` and `operate` actions; admin adds CRUD, catalog, audit, and `critical`. The backend decides using the persisted definition, not information from the browser. For `critical`, explicit confirmation and a mandatory reason are required. Every change records actor, action, resource, source, result, and IP/request ID when available.

## Allow-list Policy

A service definition selects container names/labels, not client-supplied IDs. Portainer actions restrict `operation` to `start`, `stop`, `restart`, or `logs`; Ansible restricts playbook, inventory, limit, extra-vars, and timeout to versioned/validated values. There is no `shell=True`, `command`, external path, execution URL, or interpolation of user arguments. The worker reloads the definition from the database and the queue only carries a UUID.

**Known residual risk — Portainer logs (`logs` action):** `sanitize_text` redacts *known* secret patterns (bearer/`password:`/x-api-key/vault) before persisting `docker logs` output as an `ExecutionEvent`, but that output comes from third-party containers Capataz doesn't control — if a service logs a secret in a format the regex doesn't recognize (e.g. `DB_PASS=hunter2`), it would end up persisted almost unredacted in Capataz's audit table/SSE. There is no additional mitigation today; if this is a concern for a specific service, restrict that service's `logs` action to a higher `risk_level` in the catalog, or avoid declaring the `logs` action for services known to log sensitive data in plain text.

## Docker Socket

Mounting `/var/run/docker.sock` normally amounts to granting very broad control over the Docker host and, by extension, possible root on the host. For that reason the API does not mount the socket, and V1 integrates with Portainer using a minimal token. If V2 needs to create jobs, a Docker socket proxy with allow-listed endpoints and mutual authentication, or Kubernetes Jobs, will be evaluated; see the ephemeral runner design. Don't turn the socket into a shortcut for debugging.

## SSH, sudo, and Ansible

The key belongs to an automation account, with no human login or reuse, with per-host access restricted in `authorized_keys`. `known_hosts` is pinned by fingerprint; don't disable key checking. Grant `sudo` per essential command/task, not `NOPASSWD: ALL`. Playbooks and inventories are versioned and mounted/packaged as read-only. Vault is used for automation secrets, but it does not replace Docker Secrets for control-plane credentials.

**Manual key provisioning (out of repo scope):** Capataz never generates or distributes this key pair — it only consumes the private half from the `runner_ssh_private_key` Docker secret (`runner/src/capataz_runner/config.py`, `runner/src/capataz_runner/executor.py`). Provisioning and rotation are a manual operator procedure, run outside the repo, whenever a new homelab node is added or the key rotates:

1. Generate an ed25519 key pair on a trusted admin workstation — never on the runner host or in CI:
   ```
   ssh-keygen -t ed25519 -C "capataz-automation" -f ./runner_ssh_private_key -N ""
   ```
   No passphrase (`-N ""`): the runner reads the key unattended from a Docker secret file, so the file's own access control (Docker secrets mount, `chmod 600`) is the protection layer, not a passphrase prompt.
2. Place the private half at `secrets/runner_ssh_private_key` (repo root; gitignored via `secrets/*`), `chmod 600`. It becomes the `runner_ssh_private_key` Docker secret consumed by the `runner` service.
3. Append the public half (`runner_ssh_private_key.pub`) to `~capataz_automation/.ssh/authorized_keys` on every node listed in `runner/inventories/*.yml` (the account is `ansible_user: capataz_automation`), ideally constrained with a `from="<homelab CIDR>"` prefix since this account should only ever be reached from the runner host.
4. Pin host keys: from the runner host (or an equivalent vantage point on the homelab network), run `ssh-keyscan` against every inventory host, verify each fingerprint out-of-band (console, IPMI, or another already-trusted channel — not the same network path you're trying to verify), and write the result to `secrets/runner_known_hosts`.
5. Securely wipe the local copy of the private key material from the admin workstation once it's deployed as a Docker secret (e.g. `shred -u`) — the workstation should not retain a standing copy.
6. Rotate by repeating steps 1-5 with a new key pair, deploying the new secret, verifying connectivity, and only then removing the old public key from every node's `authorized_keys`.

## SSRF and Health Probes

On import/CRUD only `http` and `https` are allowed, the destination is resolved and validated before connecting, loopback, link-local, RFC1918/cloud metadata are denied except via an explicit homelab allow-list, redirects to new destinations are prevented, and short timeouts are enforced. The refresh endpoint receives a service ID, never a URL. Responses must not reflect sensitive remote bodies.

**Known residual risk — DNS rebinding:** `validate_health_url` validates the hostname string against the suffix allow-list, but doesn't resolve or pin the IP that `httpx` ends up connecting to — a hostname allowed by suffix whose internal DNS resolves (at request time) to an unexpected private/loopback/metadata IP would pass validation. This is accepted as low risk given the homelab's closed trust model (the DNS resolving `.home.arpa` is owned by the operator), but it is a real gap against the literal SSRF requirement if that trust boundary ever changes.

## Operational Hardening

The `internal` network does not expose databases/broker; containers use a read-only filesystem where possible, temporary tmpfs, `cap_drop: ALL`, `no-new-privileges`, and CPU/memory limits. Keep images pinned, updated, and scanned with Trivy; use Dependabot and gitleaks. Periodically review Portainer tokens, Cognito groups, inventories, audit logs, and backup restores.

**Design note — no internal TLS:** `postgresql+asyncpg://`/`redis://` (API and runner) do not use TLS between services; this is accepted today because all communication happens within the unexposed Docker `internal` network. If the deployment model were to change (e.g. Postgres/Redis on a separate host without a shared trust network), parameterizable `sslmode`/`rediss://` support would need to be added before exposing those connections outside an isolated network.
