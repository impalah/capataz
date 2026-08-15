# ADR 004: Adoption of `auth-middleware` as the Cognito Identity Provider

*Language: **English** · [Español](004-auth-middleware-adoption.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-08
- **Updated:** 2026-08-10 (auth-middleware 0.5.0, generic OIDC provider)

## Context

The brief calls for using [`auth-middleware`](https://github.com/impalah/auth-middleware) for FastAPI/Starlette authentication/authorization with a Cognito provider. The published version requires `Python >= 3.14`, while the rest of the stack initially targeted `Python >= 3.12`, which prevented installing it (see history: it was temporarily replaced with an in-house adapter using `PyJWT[crypto]` behind the `IdentityProvider` port). After raising the monorepo minimum to `Python >= 3.14` (`api/.python-version`, `runner/.python-version`, `pyproject.toml`), `auth-middleware` resolution stopped failing.

## Decision

`CognitoIdentityProvider` (`api/src/capataz_api/adapters/inbound/auth.py`) delegates JWT verification and group resolution to `auth-middleware`:

- `auth_middleware.providers.aws.cognito_provider.CognitoProvider` validates the token signature against the configured user pool's JWKS (`region` + `user_pool_id`, with no explicit issuer URL).
- `auth_middleware.providers.aws.cognito_groups_provider.CognitoGroupsProvider` extracts the `cognito:groups` claim to populate RBAC groups.
- `auth_middleware.jwt_bearer_manager.JWTBearerManager` parses the `Authorization: Bearer` header and produces the `JWTAuthorizationCredentials` consumed by `CognitoProvider`.

The adapter continues to implement the same `IdentityProvider` contract consumed by the domain:

- The domain and the application services **have no knowledge** of `auth-middleware`; they depend only on the `IdentityProvider` port, exactly as before.
- `DevMockIdentityProvider` is unchanged: it still activates only with `CAPATAZ_AUTH_MODE=dev_mock` and `CAPATAZ_ENV=development`; `Settings` rejects that combination in any other environment.
- `CAPATAZ_COGNITO_ISSUER` is removed from `Settings`: `auth-middleware` derives the JWKS URL from `CAPATAZ_COGNITO_REGION` + `CAPATAZ_COGNITO_USER_POOL_ID`, not from a manually configured issuer.
- The `PyJWT[crypto]` dependency is removed from `api/pyproject.toml`; signature verification is now handled internally by `auth-middleware` (via `joserfc`).

## Consequences

- Less in-house JWT verification code to maintain/audit; signature validation, JWKS caching, and group extraction now live in a versioned external dependency.
- The `CognitoIdentityProvider` constructor changes from `(issuer, audience)` to `(region, user_pool_id, audience)`, aligned with `CognitoAuthzProviderSettings`.
- `auth-middleware` does not validate the token's `client_id`/`aud` claim against `user_pool_client_id` during `verify_token` — it only verifies the signature against the user pool's JWKS. Any valid token issued by that same user pool (for any app client) is accepted; this is library behavior, not a regression introduced here.
- If `auth-middleware` ships breaking changes, replacing the adapter is an isolated change in `adapters/inbound/auth.py` and its registration in `main.py` (`lifespan`), without touching the domain, application, or routes — the same guarantee the previous adapter already offered.

## Alternatives Considered

- **Keeping the in-house PyJWT adapter:** discarded once `Python >= 3.14` stopped blocking the dependency requested by the brief; keeping it would duplicate JWT verification logic already solved by `auth-middleware`.
- **Pinning an older `auth-middleware` version compatible with 3.12:** no such published version exists.

## Update (0.5.0): generic OIDC provider

`auth-middleware` published version `0.5.0` on PyPI (previously only available via a git pin) and adds `auth_middleware.providers.oidc.oidc_provider.OidcProvider`, a generic JWT provider for any standards-compliant OIDC issuer (Authentik, Keycloak, Auth0, Okta, ...), not just Cognito.

- `api/pyproject.toml` moves from `auth-middleware = { git = ... }` (pinned to a commit) to `auth-middleware>=0.5.0` resolved from PyPI; the `[tool.uv.sources]` git override is removed.
- `OidcIdentityProvider` is added (`api/src/capataz_api/adapters/inbound/auth.py`), built on `OidcProvider` + `OidcProviderSettings`: the JWKS is discovered from `{issuer}/.well-known/openid-configuration` (or set explicitly via `jwks_uri`), and RBAC groups are read from the configurable `groups_claim` (default `groups`) in the token itself — it does not require an additional `GroupsProvider` like Cognito does.
- `CognitoIdentityProvider` and `OidcIdentityProvider` share the `authenticate()` flow (parsing the `Authorization: Bearer` header, wrapping `InvalidTokenException` as `AuthorizationError`, mapping to `Principal`) in a private `_BearerJwtIdentityProvider` base class; they only differ in how they build `auth-middleware`'s `JWTProvider`.
- `Settings.auth_mode` now accepts `cognito | oidc | dev_mock` (previously only `cognito | dev_mock`); new fields `oidc_issuer`, `oidc_audience`, `oidc_jwks_uri`, `oidc_groups_claim`. `main.py` (`lifespan`) instantiates `OidcIdentityProvider` when `auth_mode == "oidc"`.
- Just as with Cognito, `auth-middleware` does not validate `aud` if `audience` is left empty: it is recommended to always configure `CAPATAZ_OIDC_AUDIENCE` in production.
- Step-by-step guide for registering Capataz as an OIDC application in a specific IdP (Authentik): `docs/09-authentik-oidc-setup.md`.
