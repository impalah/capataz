# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Capataz is a private web console to **view and operate, in a controlled way**, the Docker services of a distributed homelab. It aggregates service status, links to Portainer/Grafana/Loki, and orchestrates pre-declared actions with audit and RBAC. It is explicitly **not** a way to run arbitrary shell commands, execution URLs, client-supplied container IDs, or arbitrary playbooks — the API validates, persists, audits and enqueues; the `runner` executes only allow-listed actions.

Three subprojects, each with its own `Makefile`, deployed as separate Docker images:

- `api/` — FastAPI backend (Python, hexagonal architecture)
- `frontend/` — Vue 3 + Quasar SPA served by Nginx
- `runner/` — Celery worker that executes allow-listed Ansible/Portainer actions

Project docs live in `docs/` (bilingual: each doc has an `.es.md` and an `.en.md` sibling, no unsuffixed filename) and are authoritative — read `docs/01-architecture.en.md` and `docs/06-security.en.md` before making structural or security-relevant changes. `README.md`/`api/README.md`/`runner/README.md`/`frontend/README.md` are English with a `README.es.md` sibling in each directory.

## Commands

Root `Makefile` fans out to all three subprojects via Docker Compose. Run from repo root:

```bash
make build              # build the 3 images
make up / make down     # start/stop the stack
make logs service=api   # follow logs for one service
make test               # test-unit + test-integration (all projects)
make test-unit          # unit tests: api, runner, frontend
make test-integration   # api integration tests only
make test-e2e           # builds stack, runs Playwright
make lint / make format / make typecheck / make coverage
make migrate                       # alembic upgrade head, inside the running api container
make migration name="add_x"        # create an Alembic migration (delegates to api/)
make seed-catalog / make export-catalog
```

Each subproject can also be driven directly with `make -C <dir> <target>` or natively:

**api/** (Python 3.14, `uv`)
```bash
uv sync                                    # make -C api install
uv run uvicorn capataz_api.main:app --reload   # make -C api dev
uv run pytest --cov                        # make test
uv run pytest tests/unit --cov             # make test-unit
uv run pytest tests/integration --cov      # make test-integration
uv run pytest tests/unit/test_x.py::test_name -v   # single test
uv run ruff check src tests                # make lint
uv run ruff format src tests               # make format
uv run mypy src/capataz_api                # make typecheck
uv run alembic upgrade head                # make migrate
uv run alembic revision --autogenerate -m "desc"   # make migration name="desc"
```
Coverage gate is 80% (`--cov-fail-under=80`), scoped to `tests/unit`. `tool.coverage.run` omits inbound adapters/infra layers (covered by integration tests instead) — see `api/pyproject.toml`.

**runner/** (Python 3.14, `uv`)
```bash
uv sync --all-groups        # make -C runner install
uv run pytest                # make test / make test-unit
uv run pytest tests/test_x.py::test_name   # single test
uv run ruff check src tests  # make lint
uv run ruff format --check src tests  # make format (check mode)
uv run mypy                  # make typecheck
make playbook-check          # ansible-playbook --syntax-check for all 3 playbooks
make playbook-local          # dry-run playbooks against inventories/local.yml --limit local-mock
```

**frontend/** (Node 22, npm; Vue 3.5 + Quasar 2.18 + Pinia 3 + vue-router 4; Vitest + Playwright)
```bash
npm ci                       # make -C frontend install
npm run dev                  # vite on :9000
npm run build                # vue-tsc --noEmit && vite build
npm run lint                 # eslint --max-warnings=0
npm run format / format:check   # prettier
npm run typecheck            # vue-tsc --noEmit
npm run test:unit            # vitest run --coverage (already the CI form)
npx vitest run tests/unit/AuthStore.spec.ts   # single unit test file
npm run e2e                  # playwright test (make -C frontend e2e)
npx playwright test tests/e2e/capataz.spec.ts -g "name"   # single e2e test
npm run generate:openapi     # regenerate src/api/openapi.generated.ts from a live API's /openapi.json
```

No `pip`, `requirements.txt`, or Poetry — lockfiles (`api/uv.lock`, `runner/uv.lock`) are committed and consumed with `uv sync --frozen` in CI.

There is no Docker-based hot-reload override for the full stack. For hot reload, run each subproject natively (`make -C api dev`, `make -C frontend dev`, ...) — `api`/`runner` need a Postgres/Redis reachable at `localhost` for this, which neither `docker-compose.yml` nor the per-module `docker-compose.yml` in `api/`/`runner`/`frontend/` publish by default (both keep Postgres/Redis internal-only); expose those ports yourself (e.g. a local override) if you need native hot reload against a real database.

## Architecture

### Action execution flow (the core mechanism)

1. Client calls `POST /api/v1/services/{service_id}/actions/{action_key}/execute`.
2. API resolves the service and its persisted `ActionDefinition`; validates role, `risk_level`, confirmation + reason (required for `critical`), enumerated parameters and source.
3. API creates an `Execution` row (`queued`), an `AuditEvent`, and a correlation ID. **Never puts commands or secrets in the queue.**
4. API publishes exactly `{"execution_id": "<uuid>"}` to the Redis `automation` queue as Celery task `capataz_runner.tasks.process_execution`.
5. Runner atomically claims `queued -> running`, **re-reads** `Service`/`ActionDefinition` from PostgreSQL (never trusts anything from the queue payload beyond the UUID), and emits sanitized `ExecutionEvent`s.
6. A Portainer or Ansible adapter resolves only the selectors/operation/playbook/inventory/limit/extra-vars present in the allow-listed definition.
7. Runner persists a terminal state + safe summary; API exposes history via authenticated SSE.

This flow is the reason for several hard rules (see Conventions below): the queue carries only a UUID, the runner never trusts client input, and there is no code path from an HTTP request to a shell command.

### api/ — hexagonal (ports & adapters)

`api/src/capataz_api/`:
- `domain/{entities,value_objects,exceptions}` — no FastAPI/SQLAlchemy/Celery/httpx imports, ever.
- `application/{services,ports,policies,dto}` — use cases, DTOs, RBAC policy (`policies/rbac.py`), `Protocol` ports. Depends only on domain + abstractions.
- `adapters/inbound/` — `schemas.py` (request/response models, incl. the RFC 7807 `ProblemDetail`/`ValidationErrorDetail`, and per-entity response DTOs like `ServiceResponse`/`ActionResponse`/`ExecutionResponse`/`AuditEventResponse` with `from_attributes=True` so they serialize the domain dataclasses directly), `auth.py` (identity providers), `routers/` (one `APIRouter` per domain: `health.py`, `auth.py`, `services.py`, `actions.py`, `executions.py`, `catalog.py`, `audit.py`, plus shared `deps.py` for FastAPI dependencies — `repo_dependency` and the `application/services/` dependency providers). Converts HTTP to DTOs, no business logic.
- `adapters/outbound/` + `infrastructure/{database,celery,health,secrets,observability,portainer}` — SQLAlchemy async repos, Celery publisher, Portainer client, health-check HTTP, Docker-secrets file reader. Implement the `application/ports` protocols.
- `core/` — `Settings` (pydantic-settings, `env_prefix="CAPATAZ_"`), logging.
- `bootstrap/` — application wiring, kept out of `application/` to avoid clashing with the hexagonal use-case layer of the same name: `lifespan.py` (startup/shutdown, builds everything in `app.state`), `exception_handlers.py` (turns `DomainError`/`HTTPException`/`RequestValidationError`/generic `Exception` into RFC 7807 `ProblemDetail` JSON, `register_exception_handlers(app)`), `routing.py` (`register_routes(app)`, includes every router from `adapters/inbound/routers/`), `factory.py` (`create_app()` — the FastAPI instance, middleware, ties the above together). `main.py` only does `app = create_app()` plus the `run()` uvicorn entry point — see `docs/adr/005-bootstrap-and-problem-details.en.md`.

Dependency direction always points inward toward `domain`. A use case must never import a persistence/HTTP/Celery/framework symbol — add a port + adapter instead. This split is what allows swapping the persistent-worker runner for the future ephemeral executor (`docs/11-future-ephemeral-runner.en.md`) without touching use cases.

Auth: `IdentityProvider` port with three implementations selected by `CAPATAZ_AUTH_MODE` — `DevMockIdentityProvider` (reads `X-Dev-User`/`X-Dev-Groups` headers), `CognitoIdentityProvider`, and `OidcIdentityProvider` (any standards-compliant OIDC issuer — Authentik, Keycloak, Auth0, Okta, ...). Both non-mock providers delegate JWT verification to [`auth-middleware`](https://github.com/impalah/auth-middleware) (`CognitoProvider`+`CognitoGroupsProvider`, or `OidcProvider` with JWKS discovered from `{issuer}/.well-known/openid-configuration` and groups read from a configurable claim) — see `docs/adr/004-auth-middleware-adoption.en.md`. `dev_mock` is only permitted when `CAPATAZ_ENV=development` (enforced by a `Settings` field validator — do not weaken this).

RBAC is hierarchical: `capataz-viewer` (read) < `capataz-operator` (+ read/operate actions) < `capataz-admin` (+ CRUD, catalog, audit, `critical` actions). The API always makes the authorization decision server-side from the persisted definition — never trust risk_level or role from the client.

Database: Alembic migrations in `api/alembic/`; models in `infrastructure/database/models.py` (`ServiceModel`, `ActionDefinitionModel`, `ExecutionModel`, `ExecutionEventModel`, `AuditEventModel`); driver `postgresql+asyncpg`.

### runner/ — flat package, allow-list is the security boundary

`runner/src/capataz_runner/`: `celery_app.py`, `tasks.py`, `executor.py`, `actions.py`, `sanitization.py`, `database.py`, `config.py`, `models.py`, `ports.py`.

`actions.py::resolve_action` is the single enforcement point: `ALLOWED_ACTION_TYPES = {ansible, portainer}`, frozensets of exact allow-listed playbook/inventory paths (rejects absolute paths and `..` traversal), `ALLOWED_PORTAINER_OPERATIONS = {start, stop, restart, logs}`, `ALLOWED_EXTRA_VARS` validated against a safe-slug regex. Any unknown key/value raises `ActionConfigurationError`. Container targeting is similarly restricted in `executor.py::resolve_selected_container_ids` — only server-declared `service.container_selectors` (names/labels), never client-supplied container IDs.

Ansible is invoked via `asyncio.create_subprocess_exec` (never shell) with `--private-key`, `--ssh-common-args "-o StrictHostKeyChecking=yes"`, and `--vault-password-file`, all sourced from Docker secrets. All subprocess stdout/stderr passes through `sanitize_text` before being persisted as `ExecutionEvent`.

Playbooks/inventories are versioned in-repo (`runner/playbooks/`, `runner/inventories/`), never external or client-supplied paths.

### frontend/ — standard Quasar SPA

`frontend/src/`: `api/` (fetch-based `client.ts` + `capatazApi.ts` + `oidc.ts` + `runtimeConfig.ts`; base URL from `runtimeConfig.apiBaseUrl`, default `/api/v1`; every request gets `X-Request-ID`), `stores/` (Pinia: `auth`, `services`, `executions`), `pages/`, `components/`, `layouts/`, `router/`.

Frontend config (`API_BASE_URL`/`USE_MSW`/`OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_SCOPE`) is read at browser runtime from `window.__APP_CONFIG__`, populated by `/config.js` — a plain script loaded in `index.html` before the app bundle, read via `src/api/runtimeConfig.ts` — never from `import.meta.env`/Vite build-time substitution. This is what lets one `dist/` artifact deploy to any environment (Docker, S3+CloudFront, a bare Nginx) by swapping only `config.js`; see `docs/adr/007-runtime-frontend-config.en.md`. `frontend/public/config.js` ships local-dev defaults (checked into the repo, copied verbatim into `dist/`); the Docker image renders the real one at container start from `CAPATAZ_FRONTEND_*` env vars (`frontend/nginx/40-render-runtime-config.sh`, `docker-compose.yml`'s `environment:` block for the `frontend` service — not `build.args`, so changing them only needs `docker compose up -d --force-recreate frontend`, not a rebuild); a standalone static deploy edits `config.js` by hand per environment.

`USE_MSW: true` (the committed default) is a synthetic-admin, no-login mode (despite the name — there is no Mock Service Worker or in-browser mocking at all, everything hits the real API): it sets `useAuthStore().devMockEnabled`, which makes `client.ts` attach `X-Dev-User`/`X-Dev-Groups` headers matching whatever role is picked from the account-menu role switcher, authenticated server-side by the api's `CAPATAZ_AUTH_MODE=dev_mock` `DevMockIdentityProvider` (only permitted when `CAPATAZ_ENV=development` — this mode is equivalent to disabling authentication and must never be reachable from an untrusted network). Router guards run on every navigation (`router/index.ts`): `meta.public` routes (`/login`, `/auth/callback`) bypass auth entirely; otherwise it awaits `useAuthStore().load()` and, outside `dev_mock` (`USE_MSW: false`), redirects unauthenticated users to `/login`; `meta.admin` routes (`/catalog`, `/audit`) additionally require `useAuthStore().isAdmin`. Real login is a generic OIDC Authorization Code + PKCE flow (`api/oidc.ts`, config via `runtimeConfig.oidcIssuer`/`runtimeConfig.oidcClientId`) — works against Authentik/Keycloak/Auth0 (`CAPATAZ_AUTH_MODE=oidc`) or the Cognito Hosted UI (`CAPATAZ_AUTH_MODE=cognito`) since both expose a standard `.well-known/openid-configuration`. `client.ts` attaches `Authorization: Bearer <access_token>` outside `dev_mock`; `pages/LoginPage.vue` triggers the redirect and `pages/AuthCallbackPage.vue` (`/auth/callback`) exchanges the code and calls `GET /api/v1/auth/me` to populate the store. See `docs/09-authentik-oidc-setup.en.md` / `docs/10-cognito-oidc-setup.en.md`. `pages/ExecutionPage.vue` polls `GET /executions/{id}` + `GET /executions/{id}/events` every 3s while the execution is non-terminal (plus a manual refresh button), rather than using the `GET /executions/{id}/events/stream` SSE endpoint — `EventSource` cannot carry a Bearer header, so that endpoint only ever authenticated under `dev_mock`; the endpoint itself is untouched (still authenticated, still usable by API consumers that can attach a header) but the frontend no longer calls it.

`src/api/openapi.generated.ts` is generated from the live API's OpenAPI schema (`npm run generate:openapi`) — regenerate it after changing API response/request shapes rather than hand-editing.

## Conventions (from docs/03-development.en.md — treat as hard rules, not style preferences)

- `Service.id` is an immutable slug; other IDs are UUID; tables are plural snake_case.
- Never couple `application/` code to FastAPI, SQLAlchemy, Celery, or `httpx` — add a port + adapter.
- Every mutation requires identity, source, correlation ID, and an audit record.
- The queue carries only `execution_id`. The runner always re-reads the definition from PostgreSQL before acting — never trust queue payload contents beyond the UUID.
- Never add a `command` field, a client-side execution URL, secrets in YAML, or shell interpolation anywhere in the catalog/action model.
- The YAML catalog (`docs/05-yaml-catalog.en.md`) forbids passwords, tokens, DSNs, free shell, unversioned playbooks, external inventories, client-supplied container IDs, or execution URLs — validation rejects these even if the YAML is syntactically valid.
- Secrets are Docker secrets files under `/run/secrets/<name>`, read via `infrastructure/secrets/file_secret_reader`. Never put secrets in `.env`, the catalog, logs, exceptions, or responses.
- Health-check/import URLs go through SSRF defenses (scheme allow-list, no loopback/link-local/RFC1918/metadata endpoints outside an explicit homelab suffix allow-list, no redirect-following to new hosts).
- Migrations are created from `api/`, reviewed manually, and never edited once applied to a shared environment.

## CI (`.github/workflows/ci.yml`)

Four jobs: `backend` (ruff check + format --check + mypy + pytest unit w/ 80% coverage gate + pytest integration, against real Postgres/Redis service containers), `runner` (same lint/type/test pattern, no coverage gate enforced in CI), `frontend` (eslint + typecheck + vitest --coverage + vite build), `e2e` (docker compose up the full stack with CI-placeholder secrets, alembic upgrade, `playwright test`), and a `docker` image-build job. Match these exact commands when validating changes locally before pushing.
