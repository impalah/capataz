# Development

*Language: **English** · [Español](03-development.es.md)*

## Getting started

```bash
cp .env.example .env
make bootstrap
# creates secrets/* following README.md
make build
make up
make migrate
make seed-catalog
```

There's no Docker-based hot-reload override for the full stack. For hot reload, run each project natively — each has its own Makefile and, for Python, `uv`:

```bash
make -C api install
make -C runner install
make -C frontend install
make -C api dev
make -C frontend dev
```

Don't use `pip`, `requirements.txt`, or Poetry. The `api/uv.lock` and `runner/uv.lock` lockfiles are versioned and consumed with `uv sync --frozen` in CI.

## Quality workflow

```bash
make lint
make format
make typecheck
make test-unit
make test-integration
make coverage
make test-e2e
```

The `format` target modifies files; in review, use the check-mode formatter each subproject provides. Changes must keep overall coverage >=80% in backend and frontend, strict typing, and tests for the critical policies. `pre-commit` is optional but recommended for format/lint before opening a PR.

## End-to-end tests (Playwright)

The e2e suite (`frontend/tests/e2e/`) drives a real Chromium against the real stack: the API in `dev_mock` mode with `catalog/services.example.yaml` imported at startup, and the runner consuming the queue. Nothing is mocked.

**1. Prerequisites (once):** Docker with Compose v2, Node 22, `curl`, and the browser:

```bash
make -C frontend install
cd frontend && npx playwright install --with-deps chromium && cd ..
```

**2. Configuration:** `.env` copied from `.env.example`, whose defaults are exactly what the suite needs — `CAPATAZ_ENV=development`, `CAPATAZ_AUTH_MODE=dev_mock`, `CAPATAZ_CORS_ORIGINS` including `http://localhost:9000` (the Vite dev server Playwright starts), and `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. If you set `SSL_CERT_FILE`, the bundle must exist under `certs/` (`make trust-ca`).

**3. Secrets** (`secrets/`, gitignored): `postgres_password`, `redis_password`, `database_url`, `redis_url` as in the README quick start; `cognito_client_secret` (any placeholder in `dev_mock`); and the resources master key:

```bash
make bootstrap   # creates secrets/ and resources/
python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' > secrets/resources_master_key
chmod 644 secrets/*   # the containers run as uid 10001, not as your user
```

**4. Resources** (`resources/`, gitignored, mounted read-only on the api as `CAPATAZ_RESOURCES_DIR`): the example catalog declares four resources with `{file: ...}` sources, and the startup import — and therefore `/health/ready` — fails if any file is missing. Placeholders are enough for the suite:

```bash
printf 'e2e-placeholder-token\n' > resources/portainer_token
printf 'e2e-placeholder-key\n' > resources/runner_ssh_private_key
printf 'placeholder.example ssh-ed25519 AAAA\n' > resources/runner_known_hosts
printf 'e2e-placeholder-vault\n' > resources/ansible_vault_password
chmod 644 resources/*
```

With placeholders, service statuses show as unknown (Portainer rejects the token); the tests don't depend on them. If you still have the real pre-ADR-008 secrets, copying them instead (`cp secrets/{portainer_token,runner_ssh_private_key,runner_known_hosts,ansible_vault_password} resources/`) gives real statuses.

**5. Run:**

```bash
make test-e2e
```

It builds the images, runs `docker compose up -d`, waits for `http://localhost:8000/health/ready` (the api applies the migrations and imports the catalog while starting), and then runs `make -C frontend e2e`: Playwright starts `npm run dev` on port 9000, whose committed `public/config.js` already targets `http://localhost:8000/api/v1` in `dev_mock` mode, with an `es-ES` browser locale (the specs assert Spanish text). To rerun only the browser part against the running stack: `make -C frontend e2e`, or `cd frontend && npx playwright test -g "viewer"`.

**What it covers:** navigation and the confirmation of a `critical` action (it creates a real `backup` execution, processed by the runner through the `ansible` connector and its decrypted resources), a catalog v2 dry-run import, the Connectors/Resources tabs (metadata only — never resource content), and the viewer's read-only view.

**If it fails:**

- `curl http://localhost:8000/health/ready` and `docker compose logs api`: look for the migrations (`Running upgrade ... -> 20260912_0009`) and catalog import errors, which carry their YAML line (e.g. a missing file under `resources/`).
- Each failed test leaves the page snapshot in `frontend/test-results/*/error-context.md`; `cd frontend && npx playwright show-report` opens the full report.
- A database volume from an older version is migrated in place (migration `0009` is one-way). To start from scratch: `make clean` (deletes the volumes after confirmation).
- Ports 8000 or 9000 already in use: stop whatever holds them (e.g. a `make -C frontend dev`, which Playwright would otherwise reuse outside CI).

**Teardown:** `make down` keeps the data; `make clean` removes it.

## Migrations and test data

```bash
make migrate
make migration name="add_service_metadata"
make seed-catalog
make export-catalog > catalog/export.yaml
```

Migrations are created from `api`, reviewed manually, and never edited once applied to a shared environment. Fixtures contain no tokens, real private hosts, or secrets. The sample catalog contains only declarative definitions.

## Contribution conventions

- `Service.id` is an immutable slug; tables are plural snake_case, and other IDs are UUID.
- Don't couple `application` to FastAPI, SQLAlchemy, Celery, or `httpx`; add a port and an adapter instead.
- Every mutation requires identity, source, correlation ID, and an audit record.
- The queue receives only `execution_id`. Re-read the definition from PostgreSQL when executing.
- Never add a `command` field, a client-side execution URL, secrets in YAML, or shell interpolation.
- Add tests for aggregated status, RBAC, YAML validation, transitions, sanitization, and any adapters you change.

## Development environments and auth

`CAPATAZ_AUTH_MODE=dev_mock` is a strictly local convenience and is only permitted together with `CAPATAZ_ENV=development`. Test roles with:

```bash
curl -H 'X-Dev-User: ana' \
  -H 'X-Dev-Groups: capataz-admin' \
  http://localhost:8000/api/v1/services
```

Don't introduce a condition that enables this mode by absence of configuration; production must require a correctly configured Cognito.
