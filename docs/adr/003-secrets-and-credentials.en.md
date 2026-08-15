# ADR 003: Secrets as Docker Files and Credential Ownership

*Language: **English** · [Español](003-secrets-and-credentials.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

Capataz needs PostgreSQL/Redis passwords, a Portainer token, a Cognito secret, and SSH/Ansible Vault material. Environment variables, `.env`, the YAML catalog, and the repository all increase the risk of leaking these to processes, logs, backups, and version control. The API and the runner don't need exactly the same credentials.

## Decision

Secrets are stored as local, git-ignored files under `secrets/`, and Compose mounts them read-only at `/run/secrets/<name>`. The API reads them via `infrastructure/secrets/file_secret_reader.py`. `postgres_password` and `redis_password` go to their own services and consumers; `cognito_client_secret` goes only to the API; the SSH key, known_hosts, and Vault password go only to the runner. `portainer_token` goes to both the API (for status) and the runner, because V1 executes allow-listed Portainer actions directly; it is scoped to minimum privilege and will be reevaluated when the executor migrates.

## Consequences

- Secrets never travel through Git, `.env`, YAML, the queue, logs, or API responses.
- Rotation is done by replacing the file and recreating consumers, with restrictive POSIX permissions.
- The file-based format forces explicit reads and tests; it must not be converted to an environment variable for convenience.
- The limited duplication of the Portainer token is offset by minimum privilege and API/runner separation.

## Alternatives Considered

- **Environment variables:** simple, but more exposed to inspection/processes/logs and contrary to the contract.
- **Mandatory external secret manager:** desirable for larger deployments, but adds an initial dependency; the secret reader can be adapted later.
- **API executes Portainer on the runner's behalf:** centralizes the token but breaks execution separation and adds an unnecessary network hop/contract.

> Update (see ADR-006): `postgres_password`/`redis_password` now only feed the bootstrap of the
> `postgres`/`redis` containers themselves. `api`/`runner` receive the full DSN (password
> included) as a single secret — `database_url`/`redis_url` — instead of assembling it from loose
> `CAPATAZ_POSTGRES_*`/`CAPATAZ_REDIS_*` variables plus the password secret.
