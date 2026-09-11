# REST API

*Language: **English** · [Español](04-api.es.md)*

The API is versioned under `/api/v1`, listens on port `8000` by default, and publishes OpenAPI at `/api/v1/openapi.json`. All error responses use `application/problem+json` (RFC 7807). Send `X-Request-ID` if you have one; if not, the API generates one and returns it, to correlate logs, audit, and executions.

## Authentication and authorization

In the homelab, a token is validated via `CognitoIdentityProvider` (`CAPATAZ_AUTH_MODE=cognito`) or `OidcIdentityProvider` (`CAPATAZ_AUTH_MODE=oidc`), both delegating to [`auth-middleware`](https://github.com/impalah/auth-middleware)'s `OidcProvider` (as of 0.6.0 there's no dedicated `CognitoProvider` — a Cognito User Pool is, as far as the provider is concerned, just another OIDC issuer). `CognitoIdentityProvider` points `OidcProvider` at Cognito's native issuer (`https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`) with a `CognitoGroupsProvider` as `groups_provider`, because the `cognito:groups` claim normally only arrives in the ID token, not in the access token the API validates. `OidcIdentityProvider` serves any other standard OIDC issuer (Authentik, Keycloak, Auth0, Okta, ...): it discovers the JWKS from `{issuer}/.well-known/openid-configuration` (or `CAPATAZ_OIDC_JWKS_URI` if explicitly set) and reads the RBAC groups from the `CAPATAZ_OIDC_GROUPS_CLAIM` claim (default `groups`) directly from the access token — see [ADR 004](adr/004-auth-middleware-adoption.en.md) and the setup guides for [Authentik](09-authentik-oidc-setup.en.md) and [AWS Cognito](10-cognito-oidc-setup.en.md) as an OIDC provider. Both adapters implement the same `IdentityProvider` port the domain consumes. Locally, `CAPATAZ_AUTH_MODE=dev_mock` can only be enabled together with `CAPATAZ_ENV=development`; use the `X-Dev-User` and `X-Dev-Groups` headers (comma-separated groups). Never use `dev_mock` in production.

| Role | Capabilities |
|---|---|
| `capataz-viewer` | Reads services, statuses, links, executions, and events. |
| `capataz-operator` | Viewer plus `read` and `operate` actions. |
| `capataz-admin` | Operator plus CRUD, import/export, audit, and `critical` actions. |

A `critical` action requires explicit confirmation and a non-empty reason. The backend always re-validates everything, even if the UI hides controls.

## Endpoints

### Technical health

| Method | Route | Authorization | Purpose |
|---|---|---|---|
| GET | `/health/live` | infrastructure-public | Process is alive. |
| GET | `/health/ready` | infrastructure-public | PostgreSQL and Redis are available; fails while they aren't. |

### Identity

| Method | Route | Role |
|---|---|---|
| GET | `/auth/me` | viewer |

Returns `{subject, email, groups}` for the authenticated `Principal`; the frontend uses it to populate the session store after login.

### Services and status

| Method | Route | Role |
|---|---|---|
| GET | `/services?group_name=&environment=&status=&offset=&limit=` | viewer |
| POST | `/services` | admin |
| GET | `/services/{service_id}` | viewer |
| PATCH | `/services/{service_id}` | admin |
| DELETE | `/services/{service_id}` | admin, protected if there are active actions/executions |
| POST | `/services/{service_id}/refresh-status` | viewer (runs the real Portainer/health/Prometheus checks — there is no cached read) |
| GET | `/services/{service_id}/links` | viewer |

`PATCH /services/{service_id}` accepts an optional `expected_version` field (the `version` returned by a previous `GET`). If omitted, the update is last-write-wins (previous behavior). If sent and it doesn't match the row's current version, the API responds `409 Conflict` instead of silently overwriting another concurrent request's change — see CR-034 in `docs/code-review-2026-08.md`.

`service_id` is the logical, immutable slug. Refresh doesn't accept a client URL: it uses the persisted configuration. Possible statuses are `healthy`, `degraded`, `down`, `maintenance`, and `unknown`.

### Actions

| Method | Route | Role |
|---|---|---|
| GET | `/services/{service_id}/actions` | viewer |
| POST | `/services/{service_id}/actions` | admin |
| PATCH | `/services/{service_id}/actions/{action_key}` | admin |
| DELETE | `/services/{service_id}/actions/{action_key}` | admin |
| POST | `/services/{service_id}/actions/{action_key}/execute` | operator/admin depending on risk |

Execution creates an `Execution`, records an audit entry, and enqueues only its UUID. Every action references a connector with the `actions` capability (`connector` in the body); its `action_type`, returned read-only, is that connector's type. The runner executes the actions of `portainer`, `ansible` and `ssh` connectors per their declared, allow-listed configuration — never free-form commands (an `ssh` action runs only a `command_id` from `runner/ssh_commands.yml`).

Example critical request:

```http
POST /api/v1/services/open-webui/actions/backup/execute
X-Request-ID: 1cc7244e-5c29-4eea-b0da-a4d00ea204f5
X-Dev-User: ana
X-Dev-Groups: capataz-admin
Content-Type: application/json

{"source":"ui","reason":"Backup before upgrade","params":{}}
```

### Connectors

| Method | Route | Role |
|---|---|---|
| GET | `/connectors` | admin |
| POST | `/connectors` | admin |
| GET | `/connectors/{connector_id}` | admin |
| PUT | `/connectors/{connector_id}?expected_version=` | admin |
| DELETE | `/connectors/{connector_id}` | admin; `409` while any service or action uses it (the detail lists them) |

The body is a connector spec, `{id, type, description, config}`, whose `config` is validated by `type` (see [YAML Catalog](05-yaml-catalog.en.md#connectors)): referenced resources must exist and have the expected type, and URLs/hosts must pass the SSRF allow-list. `id` and `type` are immutable (`409`). Responses add `capabilities` and `version`; `expected_version` is the same optimistic-concurrency check as a service `PATCH`.

### Resources

| Method | Route | Role | Body |
|---|---|---|---|
| GET | `/resources` | admin | |
| POST | `/resources` | admin | `{id, type, description, content_base64}` |
| GET | `/resources/{resource_id}` | admin | |
| PUT | `/resources/{resource_id}/content` | admin | `{content_base64, description}` |
| DELETE | `/resources/{resource_id}` | admin; `409` while a connector uses it | |

Content travels as base64 in JSON (at most 64 KiB decoded) and is encrypted before being stored. **No endpoint returns it**: responses are `{id, type, description, fingerprint, size, source, version, created_at, updated_at}`, with a 12-character fingerprint to tell versions apart; audit records never include it.

### Executions and audit

| Method | Route | Role |
|---|---|---|
| GET | `/executions?service_id=&status=&actor=&source=&from=&to=` | viewer |
| GET | `/executions/{execution_id}` | viewer |
| GET | `/executions/{execution_id}/events` | viewer |
| POST | `/executions/{execution_id}/cancel` | depending on safe-cancellation support |
| GET | `/audit-events` | admin |

Execution statuses: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, and `rejected`. Events never include secrets, tokens, keys, or Vault values.

### Catalog

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/catalog/import` | admin | Accepts `{"yaml":"...","dry_run":true|false}` with a `version: 2` catalog; validates everything (resources, connectors, services, actions and their references) before writing anything, then upserts all or nothing. Returns `{dry_run, valid, created, updated, errors, warnings, counts}` — errors and warnings with their YAML line, `counts` per kind. |
| GET | `/catalog/export` | admin | Returns clean v2 YAML, with no resource content, secrets or transient results. |

See [yaml-catalog.md](05-yaml-catalog.en.md) for the schema, errors, and examples.

## Data conventions

- Pagination: `page` and `page_size`, with total metadata in the normalized response.
- Dates: ISO 8601 UTC.
- Internal identifiers: UUID except `Service.id` (a slug).
- Mutations: actor, source, and correlation ID are always auditable.
- Configuration fields: Pydantic validation discriminated by connector type; credentials are only ever resource references, never values.
