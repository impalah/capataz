# Infrastructure build notes — Capataz

*Language: **English** · [Español](16-infra-build-notes.es.md)*

Date: 2026-08-08

## Delivered

- Root files: `README.md`, `LICENSE` MIT, `.gitignore`, `.editorconfig`, `.env.example`, and the orchestration Makefile.
- `docker-compose.yml` for the homelab and `docker-compose.dev.yml` for local hot reload/debugging.
- A realistic declarative catalog at `catalog/services.example.yaml` with Open WebUI, Paperless-ngx, and Immich.
- Complete operational documentation under `docs/`, including architecture, API, operations, development, debugging, security, YAML, and V2 design.
- ADRs 001 (hexagonal), 002 (persistent Celery), and 003 (secrets/credential ownership).
- GitHub Actions automation: separate CI for backend, runner, frontend, E2E, Docker, and Compose validation; Dependabot; gitleaks and Trivy.
- Infrastructure utilities: an authenticated catalog client (`infra/docker/catalog_client.py`).

## Decisions made under ambiguity

1. **`internal` network with controllable egress, not `internal: true`.** The API must reach Portainer/healthchecks and the runner must reach Portainer/remote SSH; a Docker network marked `internal: true` would block that egress. The contractual `edge`/`internal` separation is kept, and PostgreSQL/Redis still have no published ports and no connection to `edge`. Job-specific egress restriction is reserved for V2 or for host firewall/policy.
2. **Contractual frontend port `8080:80`.** `frontend/Dockerfile` already builds the image on top of `nginx-unprivileged`, applies `setcap cap_net_bind_service` to the binary, and runs as user `101`. Reviewed during integration: no additional vhost is needed and it does not need to run as root; Compose only needs to grant the same capability to the container (`cap_add: NET_BIND_SERVICE` under `cap_drop: ALL`) for the real bind to `:80` to work without root privileges. The first version, which unnecessarily forced `user: "0:0"`, was corrected.
3. **Migrations before the API.** The API Dockerfile does not package Alembic or its configuration. Compose mounts `api/alembic.ini` and `api/alembic` read-only and runs `alembic upgrade head` before Uvicorn. This allows the initial catalog import once the schema exists.
4. **Import/export via the API, not a nonexistent CLI.** `make seed-catalog` and `make export-catalog` invoke the small stdlib client against authenticated endpoints. By default it uses `dev_mock` headers; with Cognito, `API_AUTHORIZATION='Bearer <token>'` is provided.
5. **Persistent V1 runner.** The future ephemeral executor is documented and decoupled but not activated. The runner keeps the SSH/Ansible secrets and its Celery healthcheck; it publishes no ports.
6. **Compose limits under `deploy.resources.limits`.** Compose v2 interprets these without requiring Swarm on modern environments; the values are deliberately conservative and should be adapted to the host.

## Validations performed

- `yaml.safe_load` succeeds for `docker-compose.yml`, `docker-compose.dev.yml`, the catalog, both workflows, and Dependabot.
- Programmatic check of the 28 contractual `CAPATAZ_*` variables, five services, two networks, seven secrets, ports, and the absence of published ports on runner/PostgreSQL/Redis.
- `python3 -m py_compile infra/docker/catalog_client.py` succeeds.
- `make -n help`, `make -n migration name=prueba`, and `make -n seed-catalog` succeed.
- Check that all 20 mandatory targets are present in the Makefile and that `uv.lock` is not ignored.

`docker compose config` could not be run, nor could containers be brought up, in this environment because the `docker` binary is not installed (exit 127). CI includes both Compose validations and the necessary test secrets files; before deploying, run `docker compose config`, `make build`, and `make up` locally, following the README.

## Limits prepared for V2, not activated

- `AutomationExecutorPort` and the `EphemeralDockerAutomationExecutor` design.
- An immutable image per job, tmpfs/read-only/no-root/cap-drop/no-new-privileges, CPU/memory/PID limits, per-execution secrets, and cleanup with `--rm`.
- Replacing the direct Docker socket with a minimal-privilege proxy, a dedicated service, or Kubernetes Jobs.
- A dedicated execution network restricted to TCP/22 of inventoried nodes.
