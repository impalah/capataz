# ADR 005: `bootstrap/` Startup Structure and RFC 7807 Errors with `ProblemDetail`

*Language: **English** · [Español](005-bootstrap-and-problem-details.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-11

## Context

`api/src/capataz_api/main.py` concentrated the construction of the FastAPI app, the `lifespan` (SQLAlchemy engine, Redis, Celery queue, `identity_provider`, `status_service`, initial catalog import), and the single exception handler (`DomainError` → ad hoc `application/problem+json`, with the body built by hand as a `dict`) in a single ~150-line file. `adapters/inbound/` also had a single `routers.py` file over 500 lines long containing every endpoint (services, actions, executions, catalog, audit, auth).

The brief asked to replicate the startup structure of another project by the same author (`lms-backend`, `src/lms/{main,application,lifespan,exception_handlers,routes}.py`), which separates main → factory → lifespan/exception_handlers/routes, and uses a `ProblemDetail` model (RFC 7807) for all error responses, not just domain ones.

## Decision

### Name collision: `application/` already exists

`lms-backend` names the module containing the `create_app()` factory `application.py`. Capataz already has an `application/` package that is the **use-case layer** of the hexagonal architecture (`application/{services,ports,policies,dto}`, see the "api/ — hexagonal" section of `CLAUDE.md`) — reusing that name for the factory would have collided with the existing import (`capataz_api.application`) and confused "hexagonal application layer" with "FastAPI app assembly," which are distinct concepts here.

We chose a new subpackage, `capataz_api/bootstrap/`, that groups all the startup wiring without touching the hexagonal layer's name:

```
capataz_api/bootstrap/
├── __init__.py        # re-exports create_app
├── lifespan.py         # asynccontextmanager: builds everything hanging off app.state
├── exception_handlers.py  # DomainError/HTTPException/RequestValidationError/Exception → ProblemDetail
├── routing.py           # register_routes(app): adds all routers from adapters/inbound/routers/
└── factory.py           # create_app(): FastAPI(), middleware, routing + exception handlers
```

`main.py` becomes a minimal entry point: `app = create_app()` plus `run()` (uvicorn).

### `routers.py` split by domain

Taking advantage of the same change, `adapters/inbound/routers.py` (a single file with every endpoint) was split into `adapters/inbound/routers/`, one router per domain, following the same pattern as `lms-backend` (one router per domain folder plus a module that only aggregates `include_router`):

- `health.py`, `auth.py`, `services.py`, `actions.py`, `executions.py`, `catalog.py`, `audit.py` — each with its own `APIRouter`.
- `deps.py` — shared FastAPI dependencies: `repo_dependency` (typed against the `Protocol` `ServiceRepository`, not the concrete class — see `docs/code-review-2026-08.md` CR-002), `current_principal`, `require()`, and the *dependency providers* for the use cases in `application/services/` (`service_application_service_dependency`, `action_application_service_dependency`, `execution_service_dependency`).

`bootstrap/routing.py::register_routes` imports each router and calls `app.include_router(...)`. The per-endpoint OpenAPI tags don't change (`Services`, `Actions`, `Executions`, `Catalog`, `Audit`, `Auth`, `Health`); the generic `"Capataz API"` tag that every endpoint carried alongside its domain tag is removed — it didn't provide any useful grouping.

### `ProblemDetail` (RFC 7807) for all errors, not just `DomainError`

Previously only `DomainError` (and its subclasses `NotFoundError`/`ConflictError`/`AuthorizationError`/`ValidationError`/`ExternalServiceError`) had a dedicated handler; `HTTPException` (e.g. the 503 from `/health/ready`), Pydantic/FastAPI validation errors, and any unforeseen exception fell through to Starlette's default responses (plain JSON, not `application/problem+json`).

`adapters/inbound/schemas.py` gains `ProblemDetail` and `ValidationErrorDetail` (replacing the unused `Problem` that existed before): `type` (URI, auto-filled with the RFC 7231/7807 section corresponding to the `status` if not specified), `title`, `status`, `detail`, `instance`, `errors` (422 only).

`bootstrap/exception_handlers.py` registers four handlers, all returning `application/problem+json`:

| Exception | Status | `type` |
|---|---|---|
| `DomainError` (by subclass: `NotFoundError`→404, `AuthorizationError`→403, `ConflictError`→409, `ValidationError`→422, `ExternalServiceError`→502, rest→400) | per table | `https://capataz.local/problems/<class-name>` (Capataz-specific, as before) |
| `HTTPException` | `exc.status_code` | corresponding RFC section |
| `RequestValidationError` | 422 | RFC 4918 §11.2 section, with `errors` populated from `exc.errors()` |
| `Exception` (catch-all) | 500 | RFC 7231 §6.6.1 section, generic `detail` — the real exception message is never leaked, only logged with a trace |

## Consequences

- `main.py` goes from ~150 to ~20 lines; each piece of startup wiring is now independently testable/replaceable (e.g. swapping `lifespan.py` for integration tests without touching `factory.py`).
- Any error not explicitly handled by an endpoint (a health 503, a Pydantic validation 422, an unforeseen `KeyError`) now responds in a consistent `ProblemDetail` format instead of mixing error formats across endpoints.
- `[tool.coverage.run].omit` in `api/pyproject.toml` is extended with `bootstrap/*` and `adapters/inbound/routers/*` — it used to select only `adapters/inbound/*` (non-recursive): the HTTP layer and the startup wiring remain covered by the Docker integration/e2e profile, not by the unit coverage gate — the same criterion that already applied to `adapters/inbound/` before the split.
- New import surface: any module that used to do `from capataz_api.adapters.inbound.routers import router, health_router` must instead import the individual domain routers from `capataz_api.adapters.inbound.routers.<domain>`. Only `main.py` (now `bootstrap/routing.py`) had that import anywhere in the repo.

## Alternatives Considered

- **Naming the factory module `application.py`, accepting the collision:** discarded; Python does not allow a module and a package with the same qualified name (`capataz_api.application`) under the same parent, and even if it did, the name would be actively confusing in a project that already uses "application" for the use-case layer.
- **Placing `lifespan.py`/`exception_handlers.py`/`routing.py`/`factory.py` directly under `capataz_api/` (no `bootstrap/` subpackage):** closer to `lms-backend`'s flat layout, but only the factory had a naming problem — we preferred grouping all four pieces of startup wiring into a single subpackage for cohesion, rather than resolving the collision ad hoc with a different name for just one piece.
- **Not splitting `routers.py`:** we considered limiting the change to the startup structure (`bootstrap/`) without touching `adapters/inbound/routers.py`; discarded at explicit request, to also replicate `lms-backend`'s router-per-domain pattern.
