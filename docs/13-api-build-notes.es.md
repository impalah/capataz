# Capataz API — build notes

*Idioma: **Español** · [English](13-api-build-notes.en.md)*

## Implementado

- Estructura hexagonal bajo `src/capataz_api`: `core`, `domain`, `application`, `adapters` e `infrastructure`.
- Modelos SQLAlchemy async y migración Alembic inicial para `services`, `action_definitions`, `executions`, `execution_events` y `audit_events`.
- API FastAPI versionada en `/api/v1`, etiquetas OpenAPI, paginación, respuestas RFC 7807 para errores de dominio y `X-Request-ID` mediante middleware.
- CRUD de servicios y acciones; catálogo YAML validado por Pydantic v2, esquema generado automáticamente, importación/exportación, `dry_run` y upsert transaccional lógico por `Service.id`.
- Importación de arranque desde `CAPATAZ_INITIAL_CATALOG_YAML_PATH`: ruta inexistente o YAML inválido abortan el arranque; los upserts son idempotentes.
- RBAC jerárquico `capataz-viewer` / `capataz-operator` / `capataz-admin`, riesgo `read` / `operate` / `critical`, confirmación y motivo obligatorio para acciones critical.
- Ejecuciones con validación allow-list, auditoría y publicación Celery de solo `{"execution_id": "..."}` a la cola exacta `automation`; la API no ejecuta automatización.
- SSE autenticado de eventos de ejecución, caché Redis de estados, agregación de estado y refresh explícito.
- Cliente Portainer async, prober HTTP con validación SSRF, links declarativos de Grafana/Loki/Portainer, sanitización de secretos/logs y lector de Docker Secrets en `/run/secrets/*`.
- `Dockerfile` multi-stage, `Makefile` solicitado, `pyproject.toml` con uv, `uv.lock` real y pruebas unitarias/integración.

## Decisión de autenticación

Se ejecutó el intento exigido:

```text
uv add 'auth-middleware @ git+https://github.com/impalah/auth-middleware.git'
```

Con el monorepo ya en `Python >=3.14` la resolución se completa sin problema. `CognitoIdentityProvider` delega en `auth-middleware` (`CognitoProvider` + `CognitoGroupsProvider`) la verificación de firma JWT contra el JWKS del user pool y la extracción de `cognito:groups`, detrás del mismo puerto `IdentityProvider`. El modo `dev_mock` usa únicamente `X-Dev-User` y `X-Dev-Groups` y Settings lo rechaza fuera de `CAPATAZ_ENV=development`. La decisión está registrada en [ADR 004](adr/004-auth-middleware-adoption.es.md) y en `api/README.md`.

## Validación ejecutada

```text
uv sync                         PASS
uv lock --check                 PASS
uv run ruff check src tests     PASS
uv run mypy src/capataz_api     PASS
uv run pytest --cov             PASS
```

Resultado de tests unitarios: **15 passed** (incluye cobertura del adapter `CognitoIdentityProvider`/`auth-middleware` en `tests/unit/test_auth.py`), con **80.63%** de cobertura de la unidad de cobertura configurada. La cobertura unitaria se concentra en dominio, políticas y adapters deterministas; controllers e infraestructura de orquestación quedan para el perfil Docker de integración. `tests/integration/test_postgres_container.py` pasa cuando Docker está disponible (arranca Testcontainers real); si no lo está, se omite automáticamente con motivo explícito. No se sustituye por SQLite para las partes dependientes de PostgreSQL (JSONB/UUID/migraciones).

## Límites deliberados de V1

- Las acciones `http`, `ssh` y `rsync` están modeladas pero se rechazan al ejecutar; solo `portainer` y `ansible` se resuelven mediante configuración allow-listed.
- La cancelación segura no está habilitada hasta que el runner exponga un contrato de revocación seguro; el endpoint responde conflicto y no pretende cancelar una tarea de forma incompleta.
- El worker/runner no se implementa en este subproyecto, por contrato del monorepo.
