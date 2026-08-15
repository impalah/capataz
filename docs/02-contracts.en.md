# Capataz — Cross-Subproject Integration Contract

*Language: **English** · [Español](02-contracts.es.md)*

This document is the shared source of truth between `api/`, `runner/`, `frontend/`, and `infra/docs`. Any subagent working on a part of the monorepo MUST respect these exact names so the whole system fits together without rework. If something isn't here, consult the full spec at `/home/user/workspace/uploaded_attachments/c894902c93be43f9a9afb6e7cfa21b96/prompt-perplexity-computer-homelab-control-plane.md`.

## 1. Docker Compose service names

- `frontend` — host port 8080 -> 80 (nginx)
- `api` — host port 8000 -> 8000 (uvicorn)
- `runner` — no published ports (Celery worker)
- `postgres` — `internal` network only, no published ports
- `redis` — `internal` network only, no published ports

Networks: `edge` (frontend, api) and `internal` (api, runner, postgres, redis).

## 2. Environment variables (non-sensitive) — `CAPATAZ_` prefix

```
CAPATAZ_ENV=development|production
CAPATAZ_LOG_LEVEL=INFO
CAPATAZ_LOG_JSON=false
CAPATAZ_API_HOST=0.0.0.0
CAPATAZ_API_PORT=8000
CAPATAZ_CORS_ORIGINS=http://localhost:8080
CAPATAZ_POSTGRES_DB=capataz     # postgres container bootstrap only; api/runner don't read this
CAPATAZ_POSTGRES_USER=capataz   # postgres container bootstrap only; api/runner don't read this
CAPATAZ_CELERY_QUEUE=automation
CAPATAZ_CELERY_CONCURRENCY=2
CAPATAZ_PORTAINER_URL=https://portainer.home.arpa
CAPATAZ_GRAFANA_URL=https://grafana.home.arpa
CAPATAZ_LOKI_URL=https://loki.home.arpa
CAPATAZ_PROMETHEUS_URL=https://prometheus.home.arpa
CAPATAZ_COGNITO_REGION=eu-west-1
CAPATAZ_COGNITO_USER_POOL_ID=
CAPATAZ_COGNITO_APP_CLIENT_ID=
CAPATAZ_OIDC_ISSUER=
CAPATAZ_OIDC_AUDIENCE=
CAPATAZ_OIDC_JWKS_URI=
CAPATAZ_OIDC_GROUPS_CLAIM=groups
CAPATAZ_AUTH_MODE=cognito|oidc|dev_mock   # dev_mock ONLY permitted if CAPATAZ_ENV=development
CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml
CAPATAZ_HTTP_TIMEOUT_SECONDS=5
CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES=.home.arpa
CAPATAZ_STATUS_CACHE_TTL_SECONDS=30
CAPATAZ_FRONTEND_API_BASE_URL=/api/v1   (frontend, served behind the nginx proxy)
CAPATAZ_FRONTEND_USE_MSW=false          (frontend; browser-side dev_mock)
CAPATAZ_FRONTEND_DEV_USER=ana.admin     (frontend; initial synthetic identity in dev_mock)
CAPATAZ_FRONTEND_OIDC_ISSUER=           (frontend; Authorization Code+PKCE login — runtime, not build-time, see ADR-007)
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=        (frontend; same public client that validates CAPATAZ_OIDC_AUDIENCE in the API)
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email groups   (frontend)
```

The six `CAPATAZ_FRONTEND_*` variables are not read by the `api`/`runner` process — they're consumed by
`frontend/nginx/40-render-runtime-config.sh` to render `config.js` at the `frontend` container's
startup time (see [ADR 007](adr/007-runtime-frontend-config.en.md)), not Vite's `import.meta.env`.
A standalone frontend deployment (outside Docker Compose) doesn't use these variables at
all — edit `config.js` directly, see [Operations](07-operations.en.md#standalone-frontend-deployment-s3cloudfront--your-own-nginx).

## 3. Docker Secrets (files under `secrets/`, mounted at `/run/secrets/<name>`)

```
database_url             -> api, runner (full SQLAlchemy DSN, password included)
redis_url                -> api, runner (full URL, password included)
postgres_password        -> postgres (for its own bootstrap only)
redis_password           -> redis (for its own --requirepass only)
portainer_token          -> api, runner (if runner calls Portainer directly; see ADR-003)
cognito_client_secret    -> api
runner_ssh_private_key   -> runner
runner_known_hosts       -> runner
ansible_vault_password   -> runner
```
`database_url`/`redis_url` are the entire DSN (scheme, user, password, host, port, DB) treated as a single secret — they are never assembled from a bare host/port/user plus a separate password secret. `postgres_password`/`redis_password` still exist only to bootstrap the `postgres`/`redis` containers themselves; they must contain the same password embedded in `database_url`/`redis_url` (the operator's responsibility when generating them, see README.md). The API reads secrets from `/run/secrets/*` via `infrastructure/secrets/file_secret_reader.py`. Never hardcode them.

## 4. RBAC roles (Cognito groups, OIDC, and dev_mock)

`capataz-viewer` < `capataz-operator` < `capataz-admin` (hierarchical, see spec §10). Headers in dev_mock: `X-Dev-User`, `X-Dev-Groups` (comma-separated) — only when `CAPATAZ_AUTH_MODE=dev_mock`. In `oidc` mode, groups are read from the `CAPATAZ_OIDC_GROUPS_CLAIM` claim (default `groups`) of the token itself.

## 5. Domain model — table names (snake_case, plural)

`services`, `action_definitions`, `executions`, `execution_events`, `audit_events`.
IDs: `services.id` is a slug string (PK). Everything else is UUID.

## 6. Shared enums (exact values, lowercase)

- ServiceStatus: `healthy`, `degraded`, `down`, `maintenance`, `unknown`
- ActionType: `portainer`, `ansible`, `http`, `ssh`, `rsync`
- RiskLevel: `read`, `operate`, `critical`
- ExecutionStatus: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `rejected`
- ExecutionSource: `ui`, `api`, `yaml`, `n8n`, `mcp`, `cron`, `alert`, `system`

## 7. REST API — `/api/v1` prefix (see spec §8 for the full endpoint list)

Port 8000. OpenAPI at `/api/v1/openapi.json`. Errors in RFC 7807 format (`application/problem+json`). Correlation header: `X-Request-ID` (if not sent, the API generates one and returns it).

## 8. Celery queue

Queue name: `automation`. Broker/result backend: Redis (`redis://:<password>@redis:6379/0`). The message the API enqueues contains only `{"execution_id": "<uuid>"}`. Celery task name: `capataz_runner.tasks.process_execution`.

## 9. Catalog YAML

Example path: `catalog/services.example.yaml` (see spec §9 for the exact shape). Root keys `version` and `services`.

## 10. Local dev port convention

- Frontend dev server (Vite/Quasar): 9000
- API: 8000
- Postgres (dev only): 5432
- Redis (dev only): 6379

## 11. License and product name

Product: **Capataz**. License: MIT (LICENSE at the repo root).
