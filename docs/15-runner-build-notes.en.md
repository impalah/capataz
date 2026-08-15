# Capataz runner — build notes

*Language: **English** · [Español](15-runner-build-notes.es.md)*

## Implemented scope

`runner/` is the V1 persistent Celery worker. It consumes exclusively from the `automation` queue and exposes the exact task `capataz_runner.tasks.process_execution`. The message contains only `execution_id`; the task atomically claims the row (`queued` → `running`) and re-reads `services`, `action_definitions`, and `executions` before executing anything.

The application uses Pydantic `Settings` with non-sensitive `CAPATAZ_*` variables. Credentials are read from files under `/run/secrets`: `database_url` and `redis_url` (full DSN, password included — see ADR-006), `portainer_token`, `runner_ssh_private_key`, `runner_known_hosts`, and `ansible_vault_password`.

`CAPATAZ_SECRETS_DIR` exists solely as an injection point for tests; in the container the default value is the Docker Secrets mount.

## Integration decisions

- **Local lightweight SQLAlchemy models.** The API does not yet expose a shared models package in this checkout. The runner defines read-only mappings
  using the contractual names `services`, `action_definitions`, `executions`, and `execution_events`; it does not create tables and contains no migrations. Schema ownership and Alembic remain with `api/`. Once a shared domain package exists, these mappings can be replaced without changing the `AutomationExecutorPort` port.
- **Portainer is called from the runner.** Only the runner receives `portainer_token`, so the API cannot execute actions. Before each operation, Portainer is queried and container IDs are resolved solely from the selectors declared on `Service`; no ID from the client, the queue, or execution parameters is ever accepted.
- **Ansible via `asyncio.create_subprocess_exec`.** `ansible-playbook` is invoked with an allow-listed argument vector, `cwd` under `/app`, a minimal environment, a timeout, and no `shell=True`. The `ansible-runner` dependency is packaged to allow a future alternative, but V1 uses the `ansible-core` executable to keep process boundaries explicit.
- **Delivery safety.** Celery uses `acks_late`, `task_reject_on_worker_lost`, a prefetch of one, soft/hard limits, publish retry, and configurable concurrency (2 by default). The conditional claim makes a second delivery harmless once the execution is `running`.
- **Secrets and observability.** All process output, results, and `ExecutionEvent`s pass through the recursive sanitizer before being persisted. Sensitive keys and Bearer/X-API-Key/password/Ansible Vault patterns are masked, along with known secret values.

## Operational artifacts

- The versioned playbooks are `restart_service.yml`, `backup_service.yml` (non-destructive simulation), and `check_connectivity.yml`. They only accept their declared variables.
- `inventories/homelab.yml` contains the fictitious hosts `node-ai-01` and `node-gpu-01`; `inventories/local.yml` is used for safe local smoke testing.
- The Dockerfile is multi-stage with Python 3.14, `uv`, `ansible-core`, `ansible-runner`, `openssh-client`, `rsync`, and `git`; it runs as UID 10001, publishes no ports, and does not install or expose `sshd`.
- The Makefile provides install, tests, lint, types, coverage, validation, local playbook execution, and Docker build targets.

## Validation performed

Run from `runner/` on 2026-08-08:

```text
uv sync --all-groups                         # successful
uv run ruff check                            # All checks passed!
uv run mypy                                  # Success: no issues found in 10 source files
uv run pytest --cov                          # 23 passed, total coverage 83.59%
make playbook-check                          # successful: 3 playbooks
make playbook-local                          # successful: 3 playbooks against local-mock
```

The sandbox does not have the Docker binary available, so `make build` (Docker image) could not be run here. The Dockerfile is ready to be validated in CI.

## Integration coverage for CI

The existing tests are unit/SQLite and validate the race claim, statuses and events, execution rehydration, the allow-list, Ansible results,
sanitization, and the Celery configuration. In CI with Docker services, an integration suite should be added against PostgreSQL 16 and Redis 7 that runs
`api/`'s migrations, publishes the real task, and checks persistence and redelivery. Real Portainer and SSH nodes should not be part of the default suite;
they are tested with a controlled HTTP transport and an explicitly authorized smoke profile.
