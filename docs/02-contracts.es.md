# Capataz — Contrato de integración entre subproyectos

*Idioma: **Español** · [English](02-contracts.en.md)*

Este documento es la fuente de verdad compartida entre `api/`, `runner/`, `frontend/` e `infra/docs`. Cualquier subagente que trabaje en una parte del monorepo DEBE respetar estos nombres exactos para que todo el sistema encaje sin retrabajo. Si algo no está aquí, consulta el spec completo en `/home/user/workspace/uploaded_attachments/c894902c93be43f9a9afb6e7cfa21b96/prompt-perplexity-computer-homelab-control-plane.md`.

## 1. Nombres de servicios Docker Compose

- `frontend` — puerto host 8080 -> 80 (nginx)
- `api` — puerto host 8000 -> 8000 (uvicorn)
- `runner` — sin puertos publicados (Celery worker)
- `postgres` — red `internal` únicamente, sin puertos publicados
- `redis` — red `internal` únicamente, sin puertos publicados

Redes: `edge` (frontend, api) y `internal` (api, runner, postgres, redis).

## 2. Variables de entorno (no sensibles) — prefijo `CAPATAZ_`

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
CAPATAZ_COGNITO_REGION=eu-west-1
CAPATAZ_COGNITO_USER_POOL_ID=
CAPATAZ_COGNITO_APP_CLIENT_ID=
CAPATAZ_OIDC_ISSUER=
CAPATAZ_OIDC_AUDIENCE=
CAPATAZ_OIDC_JWKS_URI=
CAPATAZ_OIDC_GROUPS_CLAIM=groups
CAPATAZ_AUTH_MODE=cognito|oidc|dev_mock   # dev_mock SOLO permitido si CAPATAZ_ENV=development
CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml
CAPATAZ_HTTP_TIMEOUT_SECONDS=5
CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES=.404labo.net
CAPATAZ_RESOURCES_DIR=/run/capataz-resources   # api; de dónde se leen los orígenes {file: ...} de los recursos del catálogo
CAPATAZ_ALLOW_INLINE_RESOURCES=false           # api; permite recursos {base64: ...} en el YAML con CAPATAZ_ENV=production
CAPATAZ_FRONTEND_API_BASE_URL=/api/v1   (frontend, servido tras proxy nginx)
CAPATAZ_FRONTEND_USE_MSW=false          (frontend; dev_mock del lado navegador)
CAPATAZ_FRONTEND_DEV_USER=ana.admin     (frontend; identidad sintética inicial en dev_mock)
CAPATAZ_FRONTEND_OIDC_ISSUER=           (frontend; login Authorization Code+PKCE — runtime, no build-time, ver ADR-007)
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=        (frontend; mismo client público que valida CAPATAZ_OIDC_AUDIENCE en la API)
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email groups   (frontend)
```

Las seis `CAPATAZ_FRONTEND_*` no las lee el proceso `api`/`runner` — las consume
`frontend/nginx/40-render-runtime-config.sh` para renderizar `config.js` en tiempo de arranque del
contenedor `frontend` (ver [ADR 007](adr/007-runtime-frontend-config.es.md)), no `import.meta.env` de
Vite. Un despliegue standalone del frontend (fuera de Docker Compose) no usa estas variables en
absoluto — edita `config.js` directamente, ver [Operaciones](07-operations.es.md#despliegue-standalone-del-frontend-s3cloudfront--nginx-propio).

Las URLs de Portainer, Grafana, Loki y Prometheus no son variables de entorno: son configuración
de conectores del catálogo (ver [ADR 008](adr/008-connectors-and-resources.es.md) y el
[Catálogo YAML](05-yaml-catalog.es.md)).

## 3. Docker Secrets (ficheros en `secrets/`, montados en `/run/secrets/<nombre>`)

```
database_url             -> api, runner (DSN completo de SQLAlchemy, password incluido)
redis_url                -> api, runner (URL completa, password incluido)
postgres_password        -> postgres (solo para su propio bootstrap)
redis_password           -> redis (solo para su propio --requirepass)
cognito_client_secret    -> api
resources_master_key     -> api, runner (clave(s) Fernet, una por línea: cifra/descifra los recursos del catálogo, ver ADR-008)
```
Las credenciales de integración — tokens de Portainer y Prometheus, claves privadas SSH, `known_hosts`, contraseñas de Ansible Vault — no son Docker secrets: son **recursos** del catálogo, guardados cifrados en PostgreSQL con `resources_master_key` y referenciados por conectores ([ADR 008](adr/008-connectors-and-resources.es.md)).
`database_url`/`redis_url` son el DSN entero (esquema, usuario, password, host, puerto, DB) tratado como un único secreto — no se ensamblan a partir de host/puerto/usuario sueltos más un secreto de password. `postgres_password`/`redis_password` siguen existiendo solo para inicializar los propios contenedores `postgres`/`redis`; deben contener la misma contraseña embebida en `database_url`/`redis_url` (responsabilidad del operador al generarlos, ver README.es.md). La API lee secrets desde `/run/secrets/*` vía `infrastructure/secrets/file_secret_reader.py`. Nunca hardcodear.

## 4. Roles RBAC (grupos Cognito, OIDC y dev_mock)

`capataz-viewer` < `capataz-operator` < `capataz-admin` (jerárquico, ver spec §10). Los headers en dev_mock: `X-Dev-User`, `X-Dev-Groups` (coma-separado) — solo si `CAPATAZ_AUTH_MODE=dev_mock`. En modo `oidc`, los grupos se leen de la claim `CAPATAZ_OIDC_GROUPS_CLAIM` (por defecto `groups`) del propio token.

## 5. Modelo de dominio — nombres de tabla (snake_case, plural)

`services`, `action_definitions`, `executions`, `execution_events`, `audit_events`, `connectors`, `resources`.
IDs: `services.id`, `connectors.id` y `resources.id` son slug string (PK). Resto UUID. `services.spec` guarda el spec del servicio como JSON (JSONB en PostgreSQL); `action_definitions.connector_id` referencia `connectors.id` (`ON DELETE RESTRICT`).

## 6. Enums compartidos (valores exactos, minúsculas)

- ServiceStatus: `healthy`, `degraded`, `down`, `maintenance`, `unknown`
- ActionType: `portainer`, `ansible`, `http`, `ssh`, `rsync`
- RiskLevel: `read`, `operate`, `critical`
- ExecutionStatus: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `rejected`
- ExecutionSource: `ui`, `api`, `yaml`, `n8n`, `mcp`, `cron`, `alert`, `system`
- ConnectorType: `portainer`, `prometheus`, `grafana`, `loki`, `http`, `ansible`, `ssh`
- ConnectorCapability: `status`, `actions`, `metrics`, `health`, `dashboards`, `logs`
- ResourceType: `secret`, `ssh_private_key`, `known_hosts`, `file`

## 7. API REST — prefijo `/api/v1` (ver spec §8 para lista completa de endpoints)

Puerto 8000. OpenAPI en `/api/v1/openapi.json`. Errores en formato RFC 7807 (`application/problem+json`). Header de correlación: `X-Request-ID` (si no se envía, la API genera uno y lo devuelve).

## 8. Cola Celery

Nombre de cola: `automation`. Broker/result backend: Redis (`redis://:<password>@redis:6379/0`). El mensaje encolado por la API contiene únicamente `{"execution_id": "<uuid>"}`. Nombre de tarea Celery: `capataz_runner.tasks.process_execution`.

## 9. YAML de catálogo

Ruta de ejemplo: `catalog/services.example.yaml` (forma en [Catálogo YAML](05-yaml-catalog.es.md)). Claves raíz `version` (`2`), `resources`, `connectors` y `services`. Un catálogo `version: 1` se rechaza; conviértelo con `scripts/convert_catalog_v1_to_v2.py`.

## 10. Convención de puertos en local dev

- Frontend dev server (Vite/Quasar): 9000
- API: 8000
- Postgres (solo dev): 5432
- Redis (solo dev): 6379

## 11. Licencia y nombre de producto

Producto: **Capataz**. Licencia: MIT (LICENSE en raíz).
