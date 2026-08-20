# Configurar AWS Cognito como proveedor OIDC para Capataz

*Idioma: **Español** · [English](10-cognito-oidc-setup.en.md)*

Guía paso a paso para dar de alta Capataz en un **User Pool** de AWS Cognito y activar `CAPATAZ_AUTH_MODE=cognito`. Es la contrapartida de [`docs/09-authentik-oidc-setup.md`](09-authentik-oidc-setup.es.md) — mismo flujo Authorization Code + PKCE en el frontend, mismo `/api/v1/auth/me` para poblar el store de sesión — pero con las particularidades propias de Cognito que no aplican a un issuer OIDC genérico.

## Cómo encaja con Capataz

Desde auth-middleware 0.6.0 no existe un `CognitoProvider` dedicado: un User Pool de Cognito es, a efectos de `OidcProvider`, un issuer OIDC más. `CognitoIdentityProvider` (`api/src/capataz_api/adapters/inbound/auth.py`) construye `OidcProvider` apuntando al **issuer nativo** de Cognito:

```
https://cognito-idp.{CAPATAZ_COGNITO_REGION}.amazonaws.com/{CAPATAZ_COGNITO_USER_POOL_ID}
```

(sin barra final — a diferencia del issuer de Authentik, que sí la lleva) y le pasa un `CognitoGroupsProvider` como `groups_provider`. Esto es necesario porque, a diferencia de Authentik, el claim de grupos de Cognito (`cognito:groups`) **normalmente solo aparece en el ID token, no en el access token** — y el `Authorization: Bearer` que valida la API es siempre el access token. `CognitoGroupsProvider` intenta leer `cognito:groups` del propio token igualmente (por si tu configuración sí lo incluye) y, si no está, cae a un heurístico de un único scope custom en formato `resourceServer/scopeName` — que **no** es lo mismo que pertenencia real a un grupo. Verificaremos esto con un token real en el paso 6; si hace falta, el paso 3 explica cómo forzar el claim al access token con un Lambda trigger.

> **Frontend:** el mismo cliente genérico que ya usas con Authentik (`frontend/src/api/oidc.ts`, Authorization Code + PKCE) sirve tal cual para Cognito — el Hosted UI de Cognito expone un `.well-known/openid-configuration` estándar bajo el issuer nativo. Solo cambian los valores de `CAPATAZ_FRONTEND_OIDC_*` en `config.js`, no el código.

## Requisitos previos

- Una cuenta AWS con permisos para crear/gestionar recursos de Cognito.
- Los tres roles RBAC de Capataz: `capataz-viewer` < `capataz-operator` < `capataz-admin` (jerárquico solo dentro de Capataz — en Cognito son grupos independientes, igual que en Authentik: un usuario solo necesita pertenecer al grupo de su privilegio máximo).
- Conectividad saliente desde `api`/`runner` hacia `cognito-idp.{region}.amazonaws.com` — a diferencia de Authentik, Cognito usa certificados de una CA pública estándar, así que **no** deberías necesitar `make trust-ca`/`SSL_CERT_FILE` para esto (esa guía era específica de la CA interna del homelab).

## 1. Crear el User Pool

**Amazon Cognito → User pools → Create user pool**:

- **Sign-in options**: `Email` (Capataz usa el email del claim para `Principal.email`; puedes añadir `Username` también si quieres, pero no hace falta).
- **MFA**: opcional para empezar a probar; en producción, plantéatelo obligatorio.
- **Required attributes**: `email` como mínimo.
- Guarda el **User Pool ID** (formato `{region}_XXXXXXXXX`) y la **región** — son `CAPATAZ_COGNITO_USER_POOL_ID` y `CAPATAZ_COGNITO_REGION`.

No hace falta el "initial app client" que ofrece el asistente al final — lo creamos aparte en el paso 4, con las opciones específicas que necesita una SPA con PKCE.

## 2. Crear los grupos RBAC en Cognito

**User Pool → Users and groups → Groups → Create group** — crea exactamente estos tres (nombre literal, sensible a mayúsculas, es lo que viajará en `cognito:groups`):

- `capataz-viewer`
- `capataz-operator`
- `capataz-admin`

Añade cada usuario a **un único** grupo, el de su privilegio máximo — igual que en Authentik, la jerarquía la aplica el backend de Capataz (`api/src/capataz_api/application/policies/rbac.py::has_role`), no hace falta duplicar membresías.

## 3. Si el claim `cognito:groups` no llega al access token

Compruébalo primero en el paso 6 antes de hacer nada aquí — muchas configuraciones lo resuelven solo con el paso 4 y no hace falta esto. Si el `access_token` real no trae `cognito:groups` (es el comportamiento por defecto de Cognito), la forma soportada de añadirlo es un **Pre Token Generation Lambda trigger**:

1. **User Pool → General settings → Triggers** (o **Extensions → Lambda triggers** según la versión de consola) → crea/asigna un trigger **Pre token generation**.
2. La función Lambda debe devolver el claim en `claimsToAddOrOverride` para el `accessToken` (no solo el `idToken`) — versión V2\_0 del evento del trigger, que es la que permite diferenciar id token de access token:
   ```python
   def handler(event, context):
       groups = event["request"]["groupConfiguration"]["groupsToOverride"]
       event["response"]["claimsAndScopeOverrideDetails"] = {
           "accessTokenGeneration": {
               "claimsToAddOrOverride": {"cognito:groups": groups}
           }
       }
       return event
   ```
3. Guarda y prueba de nuevo — el nuevo `access_token` debería incluir `cognito:groups`.

Si prefieres no tocar Lambdas, la alternativa es aceptar que el RBAC dependa del heurístico de scope único de `CognitoGroupsProvider` (menos flexible: un solo "grupo" por client vía un Resource Server/scope custom de Cognito) — no recomendado salvo caso de uso muy simple.

## 4. Crear el Domain (Hosted UI)

**User Pool → App integration → Domain**:

- **Cognito domain**: elige un prefijo (`https://<prefijo>.auth.{region}.amazoncognito.com`), o configura un dominio propio si ya tienes uno con certificado.

Sin esto no hay Hosted UI — el discovery document del issuer nativo (paso 6) seguirá existiendo, pero sus `authorization_endpoint`/`token_endpoint` apuntan precisamente a este dominio, así que sin él el login no tiene a dónde redirigir.

## 5. Crear el App Client

**User Pool → App integration → App clients → Create app client**:

| Campo | Valor recomendado | Motivo |
|---|---|---|
| App type | **Public client** | La SPA de Capataz no puede custodiar un `client_secret`; un client público en Cognito usa PKCE automáticamente en el intercambio de código, sin que haga falta activarlo aparte. |
| Client secret | **Don't generate a client secret** | Coherente con "Public client". |
| Authentication flows | Da igual para este flujo (son para `InitiateAuth`, la API nativa de Cognito) — no hace falta marcar ninguna. | Capataz usa Hosted UI + OAuth2, no la API `InitiateAuth`/`RespondToAuthChallenge`. |
| Allowed OAuth Flows | **Authorization code grant** (deja "Implicit grant" sin marcar) | PKCE solo aplica al flujo de código de autorización. |
| Allowed OAuth Scopes | `openid`, `email`, `profile` | Cognito no tiene un scope `groups` como Authentik — el claim de grupos llega (o no) según el paso 3, independientemente del scope pedido. **No** incluyas `groups` aquí: a diferencia de Authentik, un scope no reconocido puede hacer que Cognito rechace la petición de autorización. |
| Callback URLs | `http://localhost:8090/auth/callback` (y el dominio real cuando lo tengas) | Ruta fija que sirve `AuthCallbackPage.vue` — añade una entrada por cada origen desde el que pruebes. |
| Sign-out URLs | mismo origen, p. ej. `http://localhost:8090/` | Ver nota sobre logout más abajo — Cognito lo usa de forma distinta a Authentik. |

Guarda el **Client ID** — es `CAPATAZ_COGNITO_APP_CLIENT_ID` / `CAPATAZ_FRONTEND_OIDC_CLIENT_ID`.

> **Importante:** "Allowed OAuth Scopes" es **por App Client**, no por User Pool — que el discovery document (`.well-known/openid-configuration`) liste `profile` en `scopes_supported` solo dice que el *pool* lo soporta en general, no que tu client concreto lo tenga habilitado. Si `CAPATAZ_FRONTEND_OIDC_SCOPE` pide un scope que el client no tiene marcado, `/oauth2/authorize` redirige a tu `redirect_uri` con `error=invalid_request&error_description=invalid_scope` — sin indicar cuál de los scopes es el problema. Compruébalo probando uno a uno si te pasa:
> ```bash
> curl -sS -o /dev/null -w "%{redirect_url}\n" "https://<dominio-hosted-ui>/oauth2/authorize?client_id=<client_id>&response_type=code&scope=openid+profile&redirect_uri=<redirect_uri>&state=test&nonce=test&code_challenge=x&code_challenge_method=S256"
> ```
> Una redirección a `/login` significa que esos scopes sí están permitidos; una redirección de vuelta a tu `redirect_uri` con `error=invalid_request` señala el scope que sobra.

## 6. Configurar las variables de entorno de Capataz

Backend, en `.env`:

```bash
CAPATAZ_AUTH_MODE=cognito
CAPATAZ_COGNITO_REGION=<tu región, p. ej. eu-west-1>
CAPATAZ_COGNITO_USER_POOL_ID=<User Pool ID del paso 1>
CAPATAZ_COGNITO_APP_CLIENT_ID=<Client ID del paso 5>
```

Reinicia `api` para que reconstruya `app.state.identity_provider` (`docker compose up -d --force-recreate api`).

Frontend — igual que con Authentik, es config en tiempo de ejecución del contenedor (ver
[ADR 007](adr/007-runtime-frontend-config.es.md)):

```bash
CAPATAZ_FRONTEND_USE_MSW=false
CAPATAZ_FRONTEND_OIDC_ISSUER=https://cognito-idp.<region>.amazonaws.com/<user_pool_id>   # SIN barra final
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=<el mismo Client ID del paso 5>
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email
```

```bash
docker compose up -d --force-recreate frontend
```

## 7. Verificar la integración

1. Discovery document (issuer nativo, no el dominio Hosted UI):
   ```bash
   curl -s https://cognito-idp.<region>.amazonaws.com/<user_pool_id>/.well-known/openid-configuration | jq .issuer,.authorization_endpoint,.token_endpoint
   ```
   `issuer` debe coincidir carácter a carácter (sin barra final) con lo que construye `CognitoIdentityProvider`; `authorization_endpoint`/`token_endpoint` deben apuntar al dominio Hosted UI del paso 4, no al issuer nativo.
2. Haz login desde la UI de Capataz y, si algo falla, mira Network → la petición `POST` al `token_endpoint` (mismo procedimiento que hicimos con Authentik). Si consigues un `access_token`, decodifícalo (p. ej. en [jwt.io](https://jwt.io), sin verificar firma) y confirma:
   - `"iss"` = el issuer nativo exacto.
   - `"client_id"` (Cognito usa este claim, no siempre `"aud"`, para identificar el client en access tokens) = tu Client ID.
   - `"cognito:groups"` presente con tu grupo — si falta, vuelve al paso 3.
3. Llama a la API con ese token:
   ```bash
   curl -s -H "Authorization: Bearer <access_token>" http://localhost:8090/api/v1/auth/me
   ```
   Debe devolver `subject`/`email`/`groups`. Un 403 con `Invalid Cognito access token` en los logs de `api` casi siempre es `cognito:groups` ausente (RBAC vacío, no es lo mismo que un fallo de firma) o un desajuste de región/User Pool ID en el issuer.

## 8. Personalizar el Managed Login al estilo de Capataz

Solo aplica si el dominio Hosted UI usa **Managed Login v2** (el editor de estilos nuevo de Cognito), no el Hosted UI clásico:

```bash
aws cognito-idp describe-user-pool-domain --domain <prefijo-del-paso-4> --region <region> --query 'DomainDescription.ManagedLoginVersion'
```

Si devuelve `2`, sigue leyendo. Si devuelve `1` (o el campo no existe), es Hosted UI clásico — solo admite un logo (PNG, subido vía `SetUICustomization`, deprecada) y un bloque de CSS con clases fijas tipo `.background-customizable`/`.submitButton-customizable`; no hay editor visual ni el control fino de abajo.

`docs/assets/cognito-managed-login-branding.py` en este repo aplica el tema de Capataz contra un `ManagedLoginBranding` existente por API — es el equivalente Cognito de `docs/assets/authentik-custom.css`, pero como Managed Login no acepta CSS libre (el estilo es un JSON estructurado por componente: `form`, `primaryButton`, `pageHeader`, `pageBackground`, etc., más assets de imagen en base64 por categoría), en vez de un fichero para pegar es un script que construye ese JSON a partir de los mismos tokens que `frontend/src/styles/app.scss` (bloque `:root` = tema oscuro, `body.body--light` = tema claro) y lo aplica con `update-managed-login-branding`:

```bash
# solo mostrar el payload (dry run)
python3 docs/assets/cognito-managed-login-branding.py \
  --user-pool-id <CAPATAZ_COGNITO_USER_POOL_ID> --client-id <CAPATAZ_COGNITO_APP_CLIENT_ID> --region <region>

# aplicarlo de verdad
python3 docs/assets/cognito-managed-login-branding.py \
  --user-pool-id <CAPATAZ_COGNITO_USER_POOL_ID> --client-id <CAPATAZ_COGNITO_APP_CLIENT_ID> --region <region> --apply
```

Solo necesita el AWS CLI configurado con credenciales que puedan llamar a `cognito-idp:DescribeManagedLoginBrandingByClient`/`UpdateManagedLoginBranding` — sin `boto3`, sin dependencias del repo. Reutiliza `frontend/public/favicon.svg` como logo (form + header) y favicon — el script sanea una copia en memoria quitando `role`/`aria-label` del `<svg>` raíz antes de subirla, porque el saneador de SVG de Cognito los rechaza (`element [svg#role|aria-label] is not allowed`); el `favicon.svg` del repo no se toca. Mapea:

- Fondo de página, tarjeta del formulario, header y footer → `--color-bg`/`--color-surface`/`--color-border` (oscuro y claro).
- Botón primario → `--color-primary` por defecto, `--color-brand` (`#ff6600`) en hover/active — misma convención que `authentik-custom.css`.
- `categories.global.colorSchemeMode` → `DYNAMIC`, así que Managed Login sigue el `prefers-color-scheme` del navegador en vez de fijar un único tema.
- Radios: `12px` en la tarjeta (`--radius-lg`), `6px` en botones (`--radius-sm`).

Advertencia si tocas el script o el JSON a mano: `categories.form.displayGraphics` controla el motivo decorativo de triángulos/degradado que trae Cognito por defecto — es independiente de `components.form.logo`, y si queda en `true` se pinta por encima de `components.pageBackground.color` aunque este esté bien configurado (así es como se detectó: el fondo plano de Capataz no aparecía hasta ponerlo en `false`). El script ya lo desactiva.

Limitación conocida: `pageHeader`/`pageFooter` en Managed Login solo aceptan una imagen de logo, no hay un campo de texto para un título — así que "activar el header con Capataz" en la práctica es mostrar el icono de `favicon.svg` (el mismo hard-hat naranja del resto de la app), no un wordmark de texto. Si en algún momento quieres el nombre "Capataz" visible ahí, hace falta un SVG con el texto integrado y añadir su categoría (`PAGE_HEADER_LOGO`) al script — no implementado todavía.

Verificación: abre la URL de login del Hosted UI directamente (no hace falta el frontend de Capataz):

```
https://<dominio-hosted-ui>/login?client_id=<CAPATAZ_COGNITO_APP_CLIENT_ID>&response_type=code&scope=openid+profile+email&redirect_uri=<un-redirect-uri-registrado>
```

**Los cambios de Managed Login se sirven detrás de CloudFront** — tras aplicar, si sigues viendo el estilo anterior (o el degradado decorativo por defecto) en el navegador, haz una recarga forzada (`Ctrl+Shift+R`) antes de asumir que no se aplicó; compáralo con lo que devuelve `aws cognito-idp describe-managed-login-branding` (o un `curl` directo a la URL de login, que sí refleja el estado servidor al vuelo) para descartar caché de navegador.

## Problemas frecuentes

- **CORS al hacer `fetch` del discovery document o al intercambiar el código por el token**: verificado en vivo contra el user pool `Capataz` (`eu-west-1_T1JkF6VNE`) — no hace falta proxy ni workaround. El discovery document (`cognito-idp.<region>.amazonaws.com/<pool>/.well-known/openid-configuration`) responde `access-control-allow-origin: *`. El `token_endpoint` del dominio Hosted UI (`/oauth2/token`) sí implementa CORS correctamente: preflight `OPTIONS` y la respuesta real del `POST` devuelven `access-control-allow-origin` con el **Origin exacto de la petición** y `access-control-allow-credentials: true`. A diferencia de Authentik, esto **no está restringido a los Callback URLs registrados en el App Client** — Cognito refleja cualquier Origin que le mandes en la petición (lo comprobamos con un origen inventado y también lo aceptó), así que si ves un error de CORS aquí el problema no es de configuración de Cognito: revisa que el propio `fetch`/`XMLHttpRequest` del navegador esté bien formado (cabeceras, `Content-Type`, sin `credentials: 'include'` si no hace falta) antes de sospechar del lado del servidor.
- **Logout devuelve "Invalid request. Please check your input and try again." y redirige a `/login` en vez de cerrar sesión**: encontrado y corregido en vivo (2026-08-19) probando contra el user pool `Capataz`. Con **Managed Login v2** el discovery document **sí** incluye `end_session_endpoint` (`https://<dominio-hosted-ui>/logout`) — al contrario de lo que decía esta nota antes — pero ese endpoint **no implementa RP-initiated logout estándar**: si le mandas `id_token_hint` (con o sin `post_logout_redirect_uri`/`client_id`), rechaza la petición y rebota a `/login` con "Invalid request", conservando esos mismos parámetros en la query string (confirmado con `curl` contra el endpoint real). Solo acepta su combinación propia `client_id` + `logout_uri` — sin `id_token_hint`. `oidc.ts::logout()` ya distingue esto: `isCognitoIssuer()` detecta el issuer `cognito-idp.<region>.amazonaws.com` y usa `logout_uri` en vez de `id_token_hint`/`post_logout_redirect_uri`; contra cualquier otro IdP (Authentik, Keycloak...) sigue usando el RP-initiated logout estándar. Si ves este error, confirma que el dominio exacto (`window.location.origin`, sin barra final) esté en **Sign-out URLs** del App Client — Cognito exige coincidencia exacta también ahí.
- **RBAC vacío pese a que el usuario esté en un grupo**: revisa el paso 3 — es la causa más probable, no un problema de configuración de Capataz.

## Notas de seguridad

- No dejes `CAPATAZ_COGNITO_APP_CLIENT_ID` vacío en producción — sin él, `OidcProvider` no valida el claim de audiencia/client del token, mismo razonamiento que con `CAPATAZ_OIDC_AUDIENCE` para Authentik (ver ADR 004, sección "Consecuencias").
- No hace falta ningún secreto de Docker nuevo para este modo tampoco: client público, sin `client_secret` que gestionar en Capataz.
- Misma limitación conocida que con Authentik: el stream SSE de ejecuciones (`frontend/src/api/sse.ts`) no lleva `Authorization` fuera de `dev_mock` — ver `docs/09-authentik-oidc-setup.md#notas-de-seguridad` para el detalle, aplica igual aquí.
