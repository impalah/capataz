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
