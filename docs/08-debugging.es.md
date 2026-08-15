# Depuración

*Idioma: **Español** · [English](08-debugging.en.md)*

## Punto de partida

Comprueba primero el estado y la configuración resuelta (sin mostrar secretos):

```bash
docker compose config
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 runner
curl -i http://localhost:8000/health/live
curl -i http://localhost:8000/health/ready
```

`live` confirma que el proceso está activo; `ready` exige PostgreSQL y Redis. No trates un `live` correcto como prueba de que el sistema acepta operaciones.

## API y base de datos

- Si `ready` falla, mira primero `docker compose logs postgres` y confirma que `secrets/database_url` (usado por api/runner) y `secrets/postgres_password` (usado solo por el contenedor `postgres`) tienen la misma contraseña.
- Comprueba la conexión: `docker compose exec postgres pg_isready -U capataz -d capataz`.
- Si faltan tablas, aplica `make migrate`; no hagas `create_all` manual en producción.
- Si el catálogo de inicio falla, comprueba que `CAPATAZ_INITIAL_CATALOG_YAML_PATH` existe en el contenedor y valida el YAML antes de reintentar.
- Para problemas de CORS/proxy, verifica `CAPATAZ_CORS_ORIGINS`, `CAPATAZ_FRONTEND_API_BASE_URL` (renderizado en `config.js` en tiempo de arranque, ver [ADR 007](adr/007-runtime-frontend-config.es.md) — inspecciona `curl http://localhost:8080/config.js` directamente si dudas del valor real) y el proxy Nginx; el frontend publica 8080 y la API 8000.

## Redis, Celery y runner

- Redis: `docker compose exec redis sh -ec 'redis-cli -a "$(cat /run/secrets/redis_password)" ping'` debe devolver `PONG`.
- Revisa la configuración del broker en API y runner: cola `automation` y DSN completo (host, DB, password) leído de `/run/secrets/redis_url`; confirma que su password coincide con `secrets/redis_password` (usado solo por el contenedor `redis`).
- Si una ejecución se queda `queued`, mira que runner esté vivo y la tarea se llame `capataz_runner.tasks.process_execution`.
- Si se queda `running`, usa el timeout definido y revisa los eventos; no fuerces cambios de estado en SQL sin dejar un `AuditEvent` y una explicación de incidente.
- La cola contiene solo UUID. Si ves una definición de acción completa, comando o secreto en Redis, es un defecto de seguridad.

## Seguir una ejecución por correlation ID

1. Copia `X-Request-ID` de la respuesta que creó la ejecución o recupera `correlation_id` en `GET /api/v1/executions/{id}`.
2. Busca el valor en logs API y runner: `docker compose logs api runner | grep '<correlation-id>'`.
3. Recupera `GET /api/v1/executions/{id}/events` o abre su stream SSE autenticado.
4. Relaciona actor, definición persistida, task ID y estado sin imprimir params sensibles ni secretos.

## Portainer, healthchecks y Ansible

- Portainer: confirma `CAPATAZ_PORTAINER_URL`, conectividad desde el servicio que lo consume y que el token tiene solo permisos de lectura/operación requeridos. Revisa `environment_id`, stack y selectores declarados; nunca pruebes con un ID de contenedor arbitrario.
- Health HTTP: comprueba URL, DNS, certificado y allow-list `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES`. Las direcciones loopback, link-local y metadata cloud deben rechazarse salvo configuración explícita y revisada.
- Ansible/SSH: valida secret de clave, permisos, formato de `runner_known_hosts`, cuenta técnica, inventario y `limit`. Un fallo de host key se corrige actualizando la huella verificada, no usando `StrictHostKeyChecking=no`.
- Vault: verifica que el archivo secreto no está vacío y que los logs estén sanitizados. No imprimas variables extra ni `-vvv` sin redacción y control de acceso.

## Fallos comunes de secretos y Cognito

Los secrets son archivos exactos y se montan en `/run/secrets/`; no son variables de entorno. Revisa nombre, presencia, permisos del host y recrea consumidores tras rotar. En Cognito, verifica región, issuer, user pool, client ID y clock del host. Un 401 suele ser token/issuer/audience; un 403 indica identidad válida sin grupo requerido. `dev_mock` solo resuelve incidencias locales en desarrollo.
