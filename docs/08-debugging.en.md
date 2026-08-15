# Debugging

*Language: **English** · [Español](08-debugging.es.md)*

## Starting Point

First check the status and the resolved configuration (without showing secrets):

```bash
docker compose config
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 runner
curl -i http://localhost:8000/health/live
curl -i http://localhost:8000/health/ready
```

`live` confirms the process is up; `ready` requires PostgreSQL and Redis. Don't treat a successful `live` as proof that the system accepts operations.

## API and Database

- If `ready` fails, first look at `docker compose logs postgres` and confirm that `secrets/database_url` (used by api/runner) and `secrets/postgres_password` (used only by the `postgres` container) have the same password.
- Check the connection: `docker compose exec postgres pg_isready -U capataz -d capataz`.
- If tables are missing, apply `make migrate`; don't do a manual `create_all` in production.
- If the startup catalog fails, check that `CAPATAZ_INITIAL_CATALOG_YAML_PATH` exists in the container and validate the YAML before retrying.
- For CORS/proxy issues, check `CAPATAZ_CORS_ORIGINS`, `CAPATAZ_FRONTEND_API_BASE_URL` (rendered into `config.js` at boot time, see [ADR 007](adr/007-runtime-frontend-config.en.md) — inspect `curl http://localhost:8080/config.js` directly if you doubt the real value) and the Nginx proxy; the frontend is published on 8080 and the API on 8000.

## Redis, Celery, and Runner

- Redis: `docker compose exec redis sh -ec 'redis-cli -a "$(cat /run/secrets/redis_password)" ping'` should return `PONG`.
- Check the broker configuration in API and runner: the `automation` queue and the full DSN (host, DB, password) read from `/run/secrets/redis_url`; confirm its password matches `secrets/redis_password` (used only by the `redis` container).
- If an execution stays `queued`, check that the runner is alive and that the task is named `capataz_runner.tasks.process_execution`.
- If it stays `running`, use the defined timeout and review the events; don't force state changes in SQL without leaving an `AuditEvent` and an incident explanation.
- The queue contains only a UUID. If you see a full action definition, a command, or a secret in Redis, that's a security defect.

## Tracing an Execution by Correlation ID

1. Copy the `X-Request-ID` from the response that created the execution, or retrieve `correlation_id` from `GET /api/v1/executions/{id}`.
2. Search for the value in API and runner logs: `docker compose logs api runner | grep '<correlation-id>'`.
3. Retrieve `GET /api/v1/executions/{id}/events` or open its authenticated SSE stream.
4. Correlate actor, persisted definition, task ID, and state without printing sensitive params or secrets.

## Portainer, Healthchecks, and Ansible

- Portainer: confirm `CAPATAZ_PORTAINER_URL`, connectivity from the service that consumes it, and that the token has only the required read/operate permissions. Check `environment_id`, stack, and the declared selectors; never test with an arbitrary container ID.
- HTTP health: check URL, DNS, certificate, and the `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` allow-list. Loopback, link-local, and cloud metadata addresses must be rejected unless explicit, reviewed configuration allows them.
- Ansible/SSH: validate the key secret, permissions, `runner_known_hosts` format, technical account, inventory, and `limit`. A host key failure is fixed by updating the verified fingerprint, not by using `StrictHostKeyChecking=no`.
- Vault: verify that the secret file isn't empty and that logs are sanitized. Don't print extra variables or `-vvv` without redaction and access control.

## Common Secrets and Cognito Failures

Secrets are exact files mounted at `/run/secrets/`; they are not environment variables. Check name, presence, host permissions, and recreate consumers after rotating. In Cognito, verify region, issuer, user pool, client ID, and host clock. A 401 is usually token/issuer/audience related; a 403 indicates a valid identity without the required group. `dev_mock` only resolves local development issues.
