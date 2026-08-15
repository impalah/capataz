# ADR 004: Adopción de `auth-middleware` como proveedor de identidad Cognito

*Idioma: **Español** · [English](004-auth-middleware-adoption.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-08
- **Actualizada:** 2026-08-10 (auth-middleware 0.5.0, proveedor OIDC genérico)

## Contexto

El encargo pide usar [`auth-middleware`](https://github.com/impalah/auth-middleware) para autenticación/autorización FastAPI/Starlette con proveedor Cognito. La versión publicada exige `Python >= 3.14`, mientras el resto del stack se apoyó inicialmente en `Python >= 3.12`, lo que impidió instalarlo (ver histórico: se sustituyó temporalmente por un adapter propio con `PyJWT[crypto]` detrás del puerto `IdentityProvider`). Tras subir el mínimo del monorepo a `Python >= 3.14` (`api/.python-version`, `runner/.python-version`, `pyproject.toml`), la resolución de `auth-middleware` deja de fallar.

## Decisión

`CognitoIdentityProvider` (`api/src/capataz_api/adapters/inbound/auth.py`) delega la verificación de JWT y la resolución de grupos en `auth-middleware`:

- `auth_middleware.providers.aws.cognito_provider.CognitoProvider` valida la firma del token contra el JWKS del user pool configurado (`region` + `user_pool_id`, sin URL de issuer explícita).
- `auth_middleware.providers.aws.cognito_groups_provider.CognitoGroupsProvider` extrae la claim `cognito:groups` para poblar los grupos RBAC.
- `auth_middleware.jwt_bearer_manager.JWTBearerManager` parsea la cabecera `Authorization: Bearer` y produce las `JWTAuthorizationCredentials` que consume `CognitoProvider`.

El adapter sigue implementando el mismo contrato `IdentityProvider` que consume el dominio:

- El dominio y los application services **no conocen** `auth-middleware`; dependen solo del puerto `IdentityProvider`, igual que antes.
- `DevMockIdentityProvider` no cambia: sigue activándose únicamente con `CAPATAZ_AUTH_MODE=dev_mock` y `CAPATAZ_ENV=development`; `Settings` rechaza esa combinación en cualquier otro entorno.
- `CAPATAZ_COGNITO_ISSUER` se elimina de `Settings`: `auth-middleware` deriva la URL de JWKS de `CAPATAZ_COGNITO_REGION` + `CAPATAZ_COGNITO_USER_POOL_ID`, no de un issuer configurado a mano.
- La dependencia `PyJWT[crypto]` se retira de `api/pyproject.toml`; la verificación de firma la resuelve `auth-middleware` (vía `joserfc`) internamente.

## Consecuencias

- Menos código propio de verificación JWT que mantener/auditar; la validación de firma, caché de JWKS y extracción de grupos viven en una dependencia externa versionada.
- El constructor de `CognitoIdentityProvider` cambia de `(issuer, audience)` a `(region, user_pool_id, audience)`, alineado con `CognitoAuthzProviderSettings`.
- `auth-middleware` no valida el claim `client_id`/`aud` del token contra `user_pool_client_id` durante `verify_token` — solo verifica la firma contra el JWKS del user pool. Cualquier token válido emitido por ese mismo user pool (para cualquier app client) se acepta; esto es un comportamiento de la librería, no una regresión introducida aquí.
- Si `auth-middleware` publica cambios incompatibles, sustituir el adapter es un cambio aislado en `adapters/inbound/auth.py` y el registro en `main.py` (`lifespan`), sin tocar dominio, aplicación ni rutas — la misma garantía que ya ofrecía el adapter anterior.

## Alternativas consideradas

- **Mantener el adapter propio con PyJWT:** descartado una vez `Python >= 3.14` deja de bloquear la dependencia pedida por el encargo; mantenerlo duplicaría lógica de verificación JWT ya resuelta por `auth-middleware`.
- **Fijar una versión antigua de `auth-middleware` compatible con 3.12:** no existe tal versión publicada.

## Actualización (0.5.0): proveedor OIDC genérico

`auth-middleware` publicó su versión `0.5.0` en PyPI (antes solo estaba disponible por git pin) e incorpora `auth_middleware.providers.oidc.oidc_provider.OidcProvider`, un proveedor JWT genérico para cualquier issuer OIDC estándar (Authentik, Keycloak, Auth0, Okta, ...), no solo Cognito.

- `api/pyproject.toml` pasa de `auth-middleware = { git = ... }` (pin a un commit) a `auth-middleware>=0.5.0` resuelto desde PyPI; se elimina el `[tool.uv.sources]` con el git override.
- Se añade `OidcIdentityProvider` (`api/src/capataz_api/adapters/inbound/auth.py`), construido sobre `OidcProvider` + `OidcProviderSettings`: el JWKS se descubre desde `{issuer}/.well-known/openid-configuration` (o se fija explícitamente vía `jwks_uri`), y los grupos RBAC se leen de la claim configurable `groups_claim` (por defecto `groups`) del propio token — no requiere un `GroupsProvider` adicional como Cognito.
- `CognitoIdentityProvider` y `OidcIdentityProvider` comparten el flujo `authenticate()` (parseo del header `Authorization: Bearer`, envoltura de `InvalidTokenException` en `AuthorizationError`, mapeo a `Principal`) en una base privada `_BearerJwtIdentityProvider`; solo difieren en cómo construyen el `JWTProvider` de `auth-middleware`.
- `Settings.auth_mode` acepta ahora `cognito | oidc | dev_mock` (antes solo `cognito | dev_mock`); nuevos campos `oidc_issuer`, `oidc_audience`, `oidc_jwks_uri`, `oidc_groups_claim`. `main.py` (`lifespan`) instancia `OidcIdentityProvider` cuando `auth_mode == "oidc"`.
- Igual que con Cognito, `auth-middleware` no valida `aud` si `audience` queda vacío: se recomienda configurar siempre `CAPATAZ_OIDC_AUDIENCE` en producción.
- Guía paso a paso para dar de alta Capataz como aplicación OIDC en un IdP concreto (Authentik): `docs/09-authentik-oidc-setup.md`.
