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
CAPATAZ_AUTH_MODE=cognito|oidc|dev_mock   # dev_mock SOLO permitido si CAPATAZ_ENV=development
CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml
CAPATAZ_HTTP_TIMEOUT_SECONDS=5
CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES=.home.arpa
CAPATAZ_STATUS_CACHE_TTL_SECONDS=30
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

## 3. Docker Secrets (ficheros en `secrets/`, montados en `/run/secrets/<nombre>`)

```
database_url             -> api, runner (DSN completo de SQLAlchemy, password incluido)
redis_url                -> api, runner (URL completa, password incluido)
postgres_password        -> postgres (solo para su propio bootstrap)
redis_password           -> redis (solo para su propio --requirepass)
portainer_token          -> api, runner (si runner llama Portainer directo; ver ADR-003)
cognito_client_secret    -> api
runner_ssh_private_key   -> runner
runner_known_hosts       -> runner
ansible_vault_password   -> runner
```
`database_url`/`redis_url` son el DSN entero (esquema, usuario, password, host, puerto, DB) tratado como un único secreto — no se ensamblan a partir de host/puerto/usuario sueltos más un secreto de password. `postgres_password`/`redis_password` siguen existiendo solo para inicializar los propios contenedores `postgres`/`redis`; deben contener la misma contraseña embebida en `database_url`/`redis_url` (responsabilidad del operador al generarlos, ver README.es.md). La API lee secrets desde `/run/secrets/*` vía `infrastructure/secrets/file_secret_reader.py`. Nunca hardcodear.

## 4. Roles RBAC (grupos Cognito, OIDC y dev_mock)

`capataz-viewer` < `capataz-operator` < `capataz-admin` (jerárquico, ver spec §10). Los headers en dev_mock: `X-Dev-User`, `X-Dev-Groups` (coma-separado) — solo si `CAPATAZ_AUTH_MODE=dev_mock`. En modo `oidc`, los grupos se leen de la claim `CAPATAZ_OIDC_GROUPS_CLAIM` (por defecto `groups`) del propio token.

## 5. Modelo de dominio — nombres de tabla (snake_case, plural)

`services`, `action_definitions`, `executions`, `execution_events`, `audit_events`.
IDs: `services.id` es slug string (PK). Resto UUID.

## 6. Enums compartidos (valores exactos, minúsculas)

- ServiceStatus: `healthy`, `degraded`, `down`, `maintenance`, `unknown`
- ActionType: `portainer`, `ansible`, `http`, `ssh`, `rsync`
- RiskLevel: `read`, `operate`, `critical`
- ExecutionStatus: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `rejected`
- ExecutionSource: `ui`, `api`, `yaml`, `n8n`, `mcp`, `cron`, `alert`, `system`

## 7. API REST — prefijo `/api/v1` (ver spec §8 para lista completa de endpoints)

Puerto 8000. OpenAPI en `/api/v1/openapi.json`. Errores en formato RFC 7807 (`application/problem+json`). Header de correlación: `X-Request-ID` (si no se envía, la API genera uno y lo devuelve).

## 8. Cola Celery

Nombre de cola: `automation`. Broker/result backend: Redis (`redis://:<password>@redis:6379/0`). El mensaje encolado por la API contiene únicamente `{"execution_id": "<uuid>"}`. Nombre de tarea Celery: `capataz_runner.tasks.process_execution`.

## 9. YAML de catálogo

Ruta de ejemplo: `catalog/services.example.yaml` (ver spec §9 para forma exacta). Clave raíz `version` y `services`.

## 10. Convención de puertos en local dev

- Frontend dev server (Vite/Quasar): 9000
- API: 8000
- Postgres (solo dev): 5432
- Redis (solo dev): 6379

## 11. Licencia y nombre de producto

Producto: **Capataz**. Licencia: MIT (LICENSE en raíz).
