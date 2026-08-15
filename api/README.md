# Capataz API

*Language: **English** · [Español](README.es.md)*

Capataz's hexagonal API. Exposes `/api/v1`, persists the catalog and executions, validates actions via an allow-list, and publishes **only** `execution_id` on the `automation` queue.

## Authentication

`CognitoIdentityProvider` and `OidcIdentityProvider`, decoupled via the `IdentityProvider` port, delegate JWT verification to [`auth-middleware`](https://github.com/impalah/auth-middleware). With `CAPATAZ_AUTH_MODE=cognito`, `CognitoProvider` validates the signature against the user pool's JWKS (`CAPATAZ_COGNITO_REGION` + `CAPATAZ_COGNITO_USER_POOL_ID`) and `CognitoGroupsProvider` extracts the `cognito:groups` claim. With `CAPATAZ_AUTH_MODE=oidc`, `OidcProvider` serves any standard OIDC issuer (Authentik, Keycloak, Auth0, Okta, ...): it discovers the JWKS from `CAPATAZ_OIDC_ISSUER` (or uses `CAPATAZ_OIDC_JWKS_URI` if explicitly set) and reads groups from the `CAPATAZ_OIDC_GROUPS_CLAIM` claim. See [ADR 004](../docs/adr/004-auth-middleware-adoption.en.md).

`CAPATAZ_AUTH_MODE=dev_mock` is protected by Settings: only allowed with `CAPATAZ_ENV=development`; it uses `X-Dev-User` and `X-Dev-Groups` with comma-separated groups. Must never be used in production.

## Development

```bash
make install
CAPATAZ_ENV=development CAPATAZ_AUTH_MODE=dev_mock make dev
```

Requires PostgreSQL and Redis per the variables in [docs/02-contracts.md](../docs/02-contracts.en.md). Secrets are read only from `/run/secrets/*`.
