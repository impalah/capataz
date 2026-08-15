# API REST

*Idioma: **Español** · [English](04-api.en.md)*

La API se versiona bajo `/api/v1`, escucha por defecto en el puerto `8000` y publica OpenAPI en `/api/v1/openapi.json`. Todas las respuestas de error usan `application/problem+json` (RFC 7807). Envía `X-Request-ID` si se dispone de uno; si no, la API genera uno y lo devuelve para correlacionar logs, auditoría y ejecuciones.

## Autenticación y autorización

En homelab se valida un token mediante `CognitoIdentityProvider` (`CAPATAZ_AUTH_MODE=cognito`) o `OidcIdentityProvider` (`CAPATAZ_AUTH_MODE=oidc`), ambos delegando en [`auth-middleware`](https://github.com/impalah/auth-middleware) `OidcProvider` (desde la 0.6.0 no hay un `CognitoProvider` dedicado — un User Pool de Cognito es, a efectos del proveedor, un issuer OIDC más). `CognitoIdentityProvider` apunta `OidcProvider` al issuer nativo de Cognito (`https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`) con un `CognitoGroupsProvider` como `groups_provider`, porque el claim `cognito:groups` normalmente solo llega en el ID token, no en el access token que valida la API. `OidcIdentityProvider` sirve cualquier otro issuer OIDC estándar (Authentik, Keycloak, Auth0, Okta, ...): descubre el JWKS desde `{issuer}/.well-known/openid-configuration` (o `CAPATAZ_OIDC_JWKS_URI` si se fija explícitamente) y lee los grupos RBAC de la claim `CAPATAZ_OIDC_GROUPS_CLAIM` (por defecto `groups`) directamente del access token — ver [ADR 004](adr/004-auth-middleware-adoption.es.md) y las guías de configuración de [Authentik](09-authentik-oidc-setup.es.md) y [AWS Cognito](10-cognito-oidc-setup.es.md) como proveedor OIDC. Ambos adapters implementan el mismo puerto `IdentityProvider` que consume el dominio. En local puede activarse únicamente `CAPATAZ_ENV=development` con `CAPATAZ_AUTH_MODE=dev_mock`; usa los headers `X-Dev-User` y `X-Dev-Groups` (grupos separados por coma). No uses `dev_mock` en producción.

| Rol | Capacidades |
|---|---|
| `capataz-viewer` | Lectura de servicios, estados, enlaces, ejecuciones y eventos. |
| `capataz-operator` | Viewer más acciones `read` y `operate`. |
| `capataz-admin` | Operator más CRUD, import/export, auditoría y acciones `critical`. |

Una acción `critical` requiere confirmación explícita y un motivo no vacío. El backend vuelve a validar todo aunque la interfaz oculte controles.

## Endpoints

### Salud técnica

| Método | Ruta | Autorización | Finalidad |
|---|---|---|---|
| GET | `/health/live` | pública de infraestructura | Proceso vivo. |
| GET | `/health/ready` | pública de infraestructura | PostgreSQL y Redis disponibles; falla mientras no lo estén. |

### Identidad

| Método | Ruta | Rol |
|---|---|---|
| GET | `/auth/me` | viewer |

Devuelve `{subject, email, groups}` del `Principal` autenticado; el frontend lo usa para poblar el store de sesión tras el login.

### Servicios y estado

| Método | Ruta | Rol |
|---|---|---|
| GET | `/services?group_name=&environment=&status=&offset=&limit=` | viewer |
| POST | `/services` | admin |
| GET | `/services/{service_id}` | viewer |
| PATCH | `/services/{service_id}` | admin |
| DELETE | `/services/{service_id}` | admin, protegido si hay acciones/ejecuciones activas |
| POST | `/services/{service_id}/refresh-status` | operator/admin |
| GET | `/services/{service_id}/status` | viewer |
| GET | `/services/{service_id}/links` | viewer |

`PATCH /services/{service_id}` acepta un campo opcional `expected_version` (el `version` devuelto por un `GET` anterior). Si se omite, la actualización es last-write-wins (comportamiento previo). Si se envía y no coincide con la versión actual de la fila, la API responde `409 Conflict` en vez de sobrescribir silenciosamente el cambio de otra petición concurrente — ver CR-034 en `docs/code-review-2026-08.md`.

`service_id` es el slug lógico e inmutable. El refresh no acepta URL de cliente: usa la configuración persistida. Los estados posibles son `healthy`, `degraded`, `down`, `maintenance` y `unknown`.

### Acciones

| Método | Ruta | Rol |
|---|---|---|
| GET | `/services/{service_id}/actions` | viewer |
| POST | `/services/{service_id}/actions` | admin |
| PATCH | `/services/{service_id}/actions/{action_key}` | admin |
| DELETE | `/services/{service_id}/actions/{action_key}` | admin |
| POST | `/services/{service_id}/actions/{action_key}/execute` | operator/admin según riesgo |

La ejecución crea una `Execution`, registra auditoría y encola únicamente su UUID. Los tipos modelados son `portainer`, `ansible`, `http`, `ssh` y `rsync`; V1 ejecuta `portainer` y `ansible` según sus configuraciones declaradas, no comandos libres.

Ejemplo de solicitud crítica:

```http
POST /api/v1/services/open-webui/actions/backup/execute
X-Request-ID: 1cc7244e-5c29-4eea-b0da-a4d00ea204f5
X-Dev-User: ana
X-Dev-Groups: capataz-admin
Content-Type: application/json

{"source":"ui","reason":"Copia previa a actualización","params":{}}
```

### Ejecuciones y auditoría

| Método | Ruta | Rol |
|---|---|---|
| GET | `/executions?service_id=&status=&actor=&source=&from=&to=` | viewer |
| GET | `/executions/{execution_id}` | viewer |
| GET | `/executions/{execution_id}/events` | viewer |
| POST | `/executions/{execution_id}/cancel` | según soporte de cancelación seguro |
| GET | `/audit-events` | admin |

Estados de ejecución: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out` y `rejected`. Los eventos no incluyen secretos, tokens, claves ni valores de Vault.

### Catálogo

| Método | Ruta | Rol | Finalidad |
|---|---|---|---|
| POST | `/catalog/import` | admin | Recibe `{"yaml":"...","dry_run":true|false}`; valida YAML y hace upsert por `Service.id`. |
| GET | `/catalog/export` | admin | Devuelve YAML limpio, sin secretos ni resultados transitorios. |

Consulta [yaml-catalog.md](05-yaml-catalog.es.md) para esquema, errores y ejemplos.

## Convenciones de datos

- Paginación: `page` y `page_size`, con metadatos de total en la respuesta normalizada.
- Fechas: ISO 8601 UTC.
- Identificadores internos: UUID salvo `Service.id` (slug).
- Mutaciones: actor, source y correlation ID siempre auditables.
- Campos de configuración: validación Pydantic discriminada por `action_type`; cualquier campo secreto es inválido.
