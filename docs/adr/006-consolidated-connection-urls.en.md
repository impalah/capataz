# ADR 006: Consolidated DSN (`database_url`/`redis_url`) Instead of Loose Parts

*Language: **English** · [Español](006-consolidated-connection-urls.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-14

## Context

`api` and `runner` configured the PostgreSQL and Redis connection with four/three loose `CAPATAZ_*`
variables (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `REDIS_HOST`, `REDIS_PORT`,
`REDIS_DB`) plus the `postgres_password`/`redis_password` secrets (see ADR-003), and each service
assembled the DSN in `Settings.database_url`/`Settings.redis_url`. Operating that many scattered
parameters for a single connection target was impractical.

## Decision

`api` and `runner` now receive a single Docker secret per connection — `database_url` and `redis_url` —
containing the full DSN (scheme, user, password, host, port, and database/index). As in ADR-003, any
parameter that contains a credential is treated in its entirety as a secret: the DSN is no longer
reconstructed from host/port/user in `CAPATAZ_*` variables plus a password-only secret. The
`postgres_password`/`redis_password` secrets are kept, but exclusively for bootstrapping the
`postgres`/`redis` containers themselves (`POSTGRES_PASSWORD_FILE`, `--requirepass`); `api`/`runner`
no longer read them directly. The operator is responsible for keeping the password embedded in
`database_url`/`redis_url` in sync with `postgres_password`/`redis_password`.

`CAPATAZ_POSTGRES_DB`/`CAPATAZ_POSTGRES_USER` are kept as non-sensitive variables because they are
still needed to initialize the `postgres` container; `CAPATAZ_POSTGRES_HOST/PORT` and
`CAPATAZ_REDIS_HOST/PORT/DB` disappear entirely, since no consumer needed them outside of the DSN
itself.

## Consequences

- A single operational parameter per connection, instead of 3-4 variables plus a password secret.
- The runner still needs the "bare" password (not the whole URL) to redact it from Ansible
  output/tracebacks (`sanitization.py`); it is now extracted by parsing `database_url`/`redis_url`
  instead of being read from a separate password secret — same level of protection, a single source
  of truth.
- Rotating the password requires updating two files that must stay consistent with each other
  (`postgres_password`/`redis_password` for the engine, `database_url`/`redis_url` for the consumers),
  instead of one; this is documented in README.md.

## Alternatives Considered

- **Full DSN via a `CAPATAZ_DATABASE_URL` environment variable** (as in other services in the homelab,
  e.g. `apikey-service`): simpler, but would put the password in `.env`/Compose interpolation,
  violating the ADR-003 rule of never putting secrets outside `secrets/`.
- **DSN without password + runtime password injection**: keeps a single "operational" parameter but
  reintroduces the two-piece composition this ADR aims to eliminate.
