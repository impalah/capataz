# Capataz API — build notes

*Language: **English** · [Español](13-api-build-notes.es.md)*

## Implemented

- Hexagonal structure under `src/capataz_api`: `core`, `domain`, `application`, `adapters` and `infrastructure`.
- Async SQLAlchemy models and an initial Alembic migration for `services`, `action_definitions`, `executions`, `execution_events` and `audit_events`.
- FastAPI, versioned at `/api/v1`, OpenAPI tags, pagination, RFC 7807 responses for domain errors, and `X-Request-ID` via middleware.
- CRUD for services and actions; YAML catalog validated by Pydantic v2, auto-generated schema, import/export, `dry_run`, and logical transactional upsert by `Service.id`.
- Bootstrap import from `CAPATAZ_INITIAL_CATALOG_YAML_PATH`: a nonexistent path or invalid YAML aborts startup; upserts are idempotent.
- Hierarchical RBAC `capataz-viewer` / `capataz-operator` / `capataz-admin`, risk levels `read` / `operate` / `critical`, mandatory confirmation and reason for critical actions.
- Executions with allow-list validation, auditing, and Celery publication of only `{"execution_id": "..."}` to the exact `automation` queue; the API never executes automation itself.
- Authenticated SSE for execution events, Redis status cache, status aggregation, and explicit refresh.
- Async Portainer client, HTTP prober with SSRF validation, declarative Grafana/Loki/Portainer links, secret/log sanitization, and a Docker Secrets reader at `/run/secrets/*`.
- Multi-stage `Dockerfile`, the requested `Makefile`, `pyproject.toml` with uv, a real `uv.lock`, and unit/integration tests.

## Authentication decision

The required attempt was carried out:

```text
uv add 'auth-middleware @ git+https://github.com/impalah/auth-middleware.git'
```

With the monorepo already on `Python >=3.14`, resolution completes without issue. `CognitoIdentityProvider` delegates JWT signature verification against the user pool's JWKS and the extraction of `cognito:groups` to `auth-middleware` (`CognitoProvider` + `CognitoGroupsProvider`), behind the same `IdentityProvider` port. The `dev_mock` mode uses only `X-Dev-User` and `X-Dev-Groups`, and Settings rejects it outside `CAPATAZ_ENV=development`. The decision is recorded in [ADR 004](adr/004-auth-middleware-adoption.en.md) and in `api/README.md`.

## Validation performed

```text
uv sync                         PASS
uv lock --check                 PASS
uv run ruff check src tests     PASS
uv run mypy src/capataz_api     PASS
uv run pytest --cov             PASS
```

Unit test result: **15 passed** (includes coverage of the `CognitoIdentityProvider`/`auth-middleware` adapter in `tests/unit/test_auth.py`), with **80.63%** coverage of the configured coverage unit. Unit coverage is concentrated on domain, policies, and deterministic adapters; controllers and orchestration infrastructure are left to the integration Docker profile. `tests/integration/test_postgres_container.py` passes when Docker is available (it starts a real Testcontainers instance); when it is not, it is automatically skipped with an explicit reason. It is not replaced with SQLite for the PostgreSQL-dependent parts (JSONB/UUID/migrations).

## Deliberate V1 limits

- The `http`, `ssh`, and `rsync` action types are modeled but rejected at execution time; only `portainer` and `ansible` are resolved via allow-listed configuration.
- Safe cancellation is not enabled until the runner exposes a safe revocation contract; the endpoint responds with a conflict rather than pretending to cancel a task incompletely.
- The worker/runner is not implemented in this subproject, per the monorepo's contract.
