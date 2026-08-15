# Capataz API

*Idioma: **Español** · [English](README.md)*

API hexagonal de Capataz. Expone `/api/v1`, persiste el catálogo y las ejecuciones, valida las acciones por allow-list y publica **solo** `execution_id` en la cola `automation`.

## Autenticación

`CognitoIdentityProvider` y `OidcIdentityProvider`, desacoplados mediante el puerto `IdentityProvider`, delegan en [`auth-middleware`](https://github.com/impalah/auth-middleware) la verificación de JWT. Con `CAPATAZ_AUTH_MODE=cognito`, `CognitoProvider` valida la firma contra el JWKS del user pool (`CAPATAZ_COGNITO_REGION` + `CAPATAZ_COGNITO_USER_POOL_ID`) y `CognitoGroupsProvider` extrae la claim `cognito:groups`. Con `CAPATAZ_AUTH_MODE=oidc`, `OidcProvider` sirve cualquier issuer OIDC estándar (Authentik, Keycloak, Auth0, Okta, ...): descubre el JWKS desde `CAPATAZ_OIDC_ISSUER` (o usa `CAPATAZ_OIDC_JWKS_URI` si se fija explícitamente) y lee los grupos de la claim `CAPATAZ_OIDC_GROUPS_CLAIM`. Ver [ADR 004](../docs/adr/004-auth-middleware-adoption.es.md).

`CAPATAZ_AUTH_MODE=dev_mock` está protegido por Settings: solo se permite con `CAPATAZ_ENV=development`; utiliza `X-Dev-User` y `X-Dev-Groups` con grupos separados por comas. No debe usarse en producción.

## Desarrollo

```bash
make install
CAPATAZ_ENV=development CAPATAZ_AUTH_MODE=dev_mock make dev
```

Requiere PostgreSQL y Redis según las variables de [docs/02-contracts.md](../docs/02-contracts.es.md). Los secretos se leen únicamente de `/run/secrets/*`.
