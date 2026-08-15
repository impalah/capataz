# Notas de construcción de infraestructura — Capataz

*Idioma: **Español** · [English](16-infra-build-notes.en.md)*

Fecha: 2026-08-08

## Entregado

- Ficheros raíz: `README.md`, `LICENSE` MIT, `.gitignore`, `.editorconfig`, `.env.example` y Makefile de orquestación.
- `docker-compose.yml` para homelab y `docker-compose.dev.yml` para hot reload/depuración local.
- Catálogo declarativo realista en `catalog/services.example.yaml` con Open WebUI, Paperless-ngx e Immich.
- Documentación operativa completa en `docs/`, incluidos arquitectura, API, operaciones, desarrollo, depuración, seguridad, YAML y diseño V2.
- ADRs 001 (hexagonal), 002 (Celery persistente) y 003 (secretos/responsabilidad sobre credenciales).
- Automatización GitHub Actions: CI separado para backend, runner, frontend, E2E, Docker y validación Compose; Dependabot; gitleaks y Trivy.
- Utilidades de infraestructura: cliente autenticado de catálogo (`infra/docker/catalog_client.py`).

## Decisiones tomadas ante ambigüedades

1. **Red `internal` con egress controlable, no `internal: true`.** API debe llegar a Portainer/healthchecks y runner a Portainer/SSH remoto; una red Docker marcada `internal: true` bloquearía esa salida. Se mantiene la separación contractual `edge`/`internal`, y PostgreSQL/Redis siguen sin puertos publicados ni conexión a `edge`. La restricción de salida específica de jobs se reserva para V2 o para firewall/policy del host.
2. **Puerto contractual frontend `8080:80`.** `frontend/Dockerfile` ya construye la imagen sobre `nginx-unprivileged`, aplica `setcap cap_net_bind_service` al binario y ejecuta como usuario `101`. Revisado en integración: no hace falta ningún vhost adicional ni ejecutar como root; Compose solo necesita conceder la misma capability al contenedor (`cap_add: NET_BIND_SERVICE` bajo `cap_drop: ALL`) para que el bind a `:80` real funcione sin privilegios de root. Se corrigió la primera versión, que forzaba `user: "0:0"` innecesariamente.
3. **Migraciones antes de API.** El Dockerfile API no empaqueta Alembic ni su configuración. Compose monta `api/alembic.ini` y `api/alembic` como solo lectura y ejecuta `alembic upgrade head` antes de Uvicorn. Esto permite la importación inicial del catálogo tras existir el esquema.
4. **Import/export mediante API, no una CLI inexistente.** `make seed-catalog` y `make export-catalog` invocan el pequeño cliente stdlib contra endpoints autenticados. Por defecto usa headers de `dev_mock`; con Cognito se proporciona `API_AUTHORIZATION='Bearer <token>'`.
5. **Runner V1 persistente.** Se documenta y desacopla el futuro executor efímero, pero no se activa. El runner conserva los secretos SSH/Ansible y su healthcheck Celery; no publica puertos.
6. **Límites Compose bajo `deploy.resources.limits`.** Compose v2 los interpreta sin requerir Swarm en los entornos modernos; los valores son deliberadamente conservadores y se deben adaptar al host.

## Validaciones ejecutadas

- `yaml.safe_load` correcto para `docker-compose.yml`, `docker-compose.dev.yml`, el catálogo, ambos workflows y Dependabot.
- Comprobación programática de los 28 `CAPATAZ_*` del contrato, cinco servicios, dos redes, siete secrets, puertos y ausencia de puertos en runner/PostgreSQL/Redis.
- `python3 -m py_compile infra/docker/catalog_client.py` correcto.
- `make -n help`, `make -n migration name=prueba` y `make -n seed-catalog` correctos.
- Comprobación de que los 20 objetivos obligatorios están en el Makefile y de que `uv.lock` no se ignora.

No se pudo ejecutar `docker compose config` ni levantar contenedores en este entorno porque el binario `docker` no está instalado (exit 127). La CI incluye ambas validaciones de Compose y los ficheros de secretos de prueba necesarios; antes de desplegar, ejecutar localmente `docker compose config`, `make build` y `make up` siguiendo README.

## Límites preparados para V2, no activados

- `AutomationExecutorPort` y el diseño `EphemeralDockerAutomationExecutor`.
- Imagen inmutable por job, tmpfs/read-only/no-root/cap-drop/no-new-privileges, límites CPU/memoria/PIDs, secrets por ejecución y limpieza con `--rm`.
- Sustitución de socket Docker directo por proxy de mínimo privilegio, servicio dedicado o Kubernetes Jobs.
- Red de ejecución dedicada y restringida a TCP/22 de nodos inventariados.
