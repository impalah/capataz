# ADR 005: Estructura de arranque `bootstrap/` y errores RFC 7807 con `ProblemDetail`

*Idioma: **Español** · [English](005-bootstrap-and-problem-details.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-11

## Contexto

`api/src/capataz_api/main.py` concentraba la construcción de la app FastAPI, el `lifespan` (motor SQLAlchemy, Redis, cola Celery, `identity_provider`, `status_service`, import inicial del catálogo) y el único manejador de excepciones (`DomainError` → `application/problem+json` ad hoc, con el cuerpo construido a mano como `dict`) en un solo fichero de ~150 líneas. `adapters/inbound/` tenía además un único `routers.py` de más de 500 líneas con todos los endpoints (servicios, acciones, ejecuciones, catálogo, auditoría, auth).

Se pidió replicar la estructura de arranque de otro proyecto del mismo autor (`lms-backend`, `src/lms/{main,application,lifespan,exception_handlers,routes}.py`), que separa main → factory → lifespan/exception_handlers/routes, y que usa un modelo `ProblemDetail` (RFC 7807) para todas las respuestas de error, no solo las de dominio.

## Decisión

### Colisión de nombres: `application/` ya existe

`lms-backend` llama `application.py` al módulo que contiene el factory `create_app()`. Capataz ya tiene un paquete `application/` que es la **capa de casos de uso** de la arquitectura hexagonal (`application/{services,ports,policies,dto}`, ver sección "api/ — hexagonal" de `CLAUDE.md`) — reutilizar ese nombre para el factory habría colisionado con el import existente (`capataz_api.application`) y confundido "capa de aplicación hexagonal" con "ensamblado de la app FastAPI", que son conceptos distintos aquí.

Se optó por un subpaquete nuevo, `capataz_api/bootstrap/`, que agrupa todo el cableado de arranque sin tocar el nombre de la capa hexagonal:

```
capataz_api/bootstrap/
├── __init__.py        # re-exporta create_app
├── lifespan.py         # asynccontextmanager: construye todo lo que cuelga de app.state
├── exception_handlers.py  # DomainError/HTTPException/RequestValidationError/Exception → ProblemDetail
├── routing.py           # register_routes(app): agrega todos los routers de adapters/inbound/routers/
└── factory.py           # create_app(): FastAPI(), middleware, routing + exception handlers
```

`main.py` queda como punto de entrada mínimo: `app = create_app()` más `run()` (uvicorn).

### `routers.py` dividido por dominio

Aprovechando el mismo cambio, `adapters/inbound/routers.py` (un único fichero con todos los endpoints) se dividió en `adapters/inbound/routers/`, un router por dominio, siguiendo el mismo patrón que `lms-backend` (un router por carpeta de dominio + un módulo que solo agrega `include_router`):

- `health.py`, `auth.py`, `services.py`, `actions.py`, `executions.py`, `catalog.py`, `audit.py` — cada uno su propio `APIRouter`.
- `deps.py` — dependencias FastAPI compartidas: `repo_dependency` (tipado contra el `Protocol` `ServiceRepository`, no la clase concreta — ver `docs/code-review-2026-08.md` CR-002), `current_principal`, `require()`, y los *dependency providers* de los casos de uso de `application/services/` (`service_application_service_dependency`, `action_application_service_dependency`, `execution_service_dependency`).

`bootstrap/routing.py::register_routes` importa cada router y hace `app.include_router(...)`. Los tags de OpenAPI por endpoint no cambian (`Services`, `Actions`, `Executions`, `Catalog`, `Audit`, `Auth`, `Health`); se elimina el tag genérico `"Capataz API"` que llevaban todos los endpoints además de su tag de dominio — no aportaba agrupación útil.

### `ProblemDetail` (RFC 7807) para todos los errores, no solo `DomainError`

Antes solo `DomainError` (y sus subclases `NotFoundError`/`ConflictError`/`AuthorizationError`/`ValidationError`/`ExternalServiceError`) tenían un manejador dedicado; `HTTPException` (p. ej. el 503 de `/health/ready`), los errores de validación de Pydantic/FastAPI y cualquier excepción no prevista caían en las respuestas por defecto de Starlette (JSON plano, no `application/problem+json`).

`adapters/inbound/schemas.py` gana `ProblemDetail` y `ValidationErrorDetail` (reemplazan el `Problem` que existía sin usar): `type` (URI, se autocompleta a la sección RFC 7231/7807 correspondiente al `status` si no se especifica), `title`, `status`, `detail`, `instance`, `errors` (solo en 422).

`bootstrap/exception_handlers.py` registra cuatro manejadores, todos devolviendo `application/problem+json`:

| Excepción | Status | `type` |
|---|---|---|
| `DomainError` (por subclase: `NotFoundError`→404, `AuthorizationError`→403, `ConflictError`→409, `ValidationError`→422, `ExternalServiceError`→502, resto→400) | según tabla | `https://capataz.local/problems/<nombre-clase>` (específico de Capataz, como antes) |
| `HTTPException` | `exc.status_code` | sección RFC correspondiente |
| `RequestValidationError` | 422 | sección RFC 4918 §11.2, con `errors` poblado desde `exc.errors()` |
| `Exception` (catch-all) | 500 | sección RFC 7231 §6.6.1, `detail` genérico — nunca se filtra el mensaje real de la excepción, solo se loguea con traza |

## Consecuencias

- `main.py` pasa de ~150 a ~20 líneas; cada pieza de arranque es ahora testeable/sustituible de forma aislada (p. ej. sustituir `lifespan.py` para tests de integración sin tocar `factory.py`).
- Cualquier error no manejado explícitamente por un endpoint (503 de salud, 422 de validación de Pydantic, un `KeyError` no previsto) ahora responde en formato `ProblemDetail` consistente en vez de mezclar formatos de error entre endpoints.
- `[tool.coverage.run].omit` en `api/pyproject.toml` se amplía con `bootstrap/*` y `adapters/inbound/routers/*`, seleccionaba solo `adapters/inbound/*` (no recursivo): la capa HTTP y el cableado de arranque siguen cubiertos por el perfil de integración/e2e Docker, no por el gate de cobertura unitaria — mismo criterio que ya aplicaba a `adapters/inbound/` antes de la división.
- Nueva superficie de import: cualquier módulo que antes hiciera `from capataz_api.adapters.inbound.routers import router, health_router` debe importar los routers de dominio individuales desde `capataz_api.adapters.inbound.routers.<dominio>` en su lugar. Solo `main.py` (ahora `bootstrap/routing.py`) tenía ese import en todo el repo.

## Alternativas consideradas

- **Llamar `application.py` al factory, aceptando la colisión:** descartado; Python no permite un módulo y un paquete con el mismo nombre calificado (`capataz_api.application`) en el mismo padre, y aunque lo permitiera, el nombre sería activamente confuso en un proyecto que ya usa "application" para la capa de casos de uso.
- **Meter `lifespan.py`/`exception_handlers.py`/`routing.py`/`factory.py` sueltos directamente en `capataz_api/` (sin subpaquete `bootstrap/`):** más fiel a la disposición plana de `lms-backend`, pero solo el factory tenía problema de nombre — se prefirió agrupar las cuatro piezas de cableado de arranque en un único subpaquete por cohesión, en vez de resolver la colisión ad hoc con un nombre distinto para una sola pieza.
- **No dividir `routers.py`:** se planteó limitar el cambio a la estructura de arranque (`bootstrap/`) sin tocar `adapters/inbound/routers.py`; se descartó a petición explícita para replicar también el patrón de router-por-dominio de `lms-backend`.
