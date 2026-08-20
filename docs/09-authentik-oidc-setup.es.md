# Configurar Authentik como proveedor OIDC para Capataz

*Idioma: **Español** · [English](09-authentik-oidc-setup.en.md)*

Guía paso a paso para dar de alta Capataz como aplicación OIDC en [Authentik](https://goauthentik.io/) y activar `CAPATAZ_AUTH_MODE=oidc` (`OidcIdentityProvider`, ver [ADR 004](adr/004-auth-middleware-adoption.es.md)). Authentik es solo un ejemplo de issuer estándar — el mismo procedimiento conceptual aplica a Keycloak, Auth0 u Okta, ya que `OidcIdentityProvider` no asume nada específico de un proveedor.

## Cómo encaja con Capataz

`OidcIdentityProvider` verifica el `access_token` recibido en `Authorization: Bearer <token>` contra el issuer OIDC configurado:

1. Descubre el JWKS desde `{CAPATAZ_OIDC_ISSUER}/.well-known/openid-configuration` (a menos que fijes `CAPATAZ_OIDC_JWKS_URI` explícitamente).
2. Verifica la firma (solo `RS256`) y los claims `iss`/`aud` (`aud` debe coincidir con `CAPATAZ_OIDC_AUDIENCE`, el `client_id`).
3. Lee el rol RBAC directamente del claim `CAPATAZ_OIDC_GROUPS_CLAIM` (por defecto `groups`) **del propio `access_token`** — no hace una llamada adicional a `/userinfo` ni usa un `GroupsProvider` externo como en Cognito.

Por tanto, el requisito clave en el lado de Authentik no es solo "crear una aplicación OIDC", sino asegurarse de que el `access_token` que Authentik emite (no solo el `id_token`) incluye el claim `groups` con los nombres exactos de grupo `capataz-viewer` / `capataz-operator` / `capataz-admin`.

> **Frontend:** el login en el navegador (`frontend/src/api/oidc.ts`) hace Authorization Code + PKCE genérico contra el `OIDC_ISSUER`/`OIDC_CLIENT_ID` de `config.js` (renderizado desde `CAPATAZ_FRONTEND_OIDC_ISSUER`/`CAPATAZ_FRONTEND_OIDC_CLIENT_ID`, ver [ADR 007](adr/007-runtime-frontend-config.es.md)) y adjunta el `access_token` como `Authorization: Bearer` en cada llamada (`frontend/src/api/client.ts`); solo se activa cuando `CAPATAZ_FRONTEND_USE_MSW=false`. El callback vive en la ruta `/auth/callback` (`frontend/src/pages/AuthCallbackPage.vue`) — es la URL que hay que registrar como Redirect URI en el paso 3.

## Requisitos previos

- Una instancia de Authentik con acceso de administrador (`https://authentik.home.arpa` en los ejemplos siguientes).
- Los tres roles RBAC de Capataz definidos en `docs/02-contracts.md`: `capataz-viewer` < `capataz-operator` < `capataz-admin` (jerárquico solo dentro de Capataz — en Authentik son grupos independientes, ver nota en el paso 1).
- Conectividad saliente desde el contenedor `api` hacia Authentik (para el discovery document y el JWKS) — si Authentik está en `.home.arpa`, ya cubierto por `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` para los health checks, pero la verificación OIDC en sí no pasa por esas defensas SSRF (solo se aplican a URLs de servicio/health, no a la validación de tokens).
- Si tu Authentik (o Portainer/Grafana/Loki/Prometheus) está detrás de un certificado firmado por una **CA interna** (no pública) del homelab, `api`/`runner` necesitan confiar en ella explícitamente — ver "Problemas frecuentes" más abajo (`make trust-ca`). Sin esto, la petición al discovery document falla con `CERTIFICATE_VERIFY_FAILED` aunque el navegador no se queje (el navegador ya confía en tu CA; el contenedor Python, no, por defecto).

## 1. Crear los grupos RBAC en Authentik

En **Directory → Groups**, crea exactamente estos tres grupos (el nombre literal es el valor que viajará en el claim `groups`, sensible a mayúsculas):

- `capataz-viewer`
- `capataz-operator`
- `capataz-admin`

Añade cada usuario a **un único** grupo, el que corresponda a su privilegio máximo. La jerarquía (admin implica operator implica viewer) la aplica el backend de Capataz (`api/src/capataz_api/application/policies/rbac.py::has_role`), comprobando pertenencia a un conjunto de grupos — **no** hace falta añadir a un admin también a `capataz-operator`/`capataz-viewer` en Authentik.

## 2. Exponer el claim `groups` en el access token

Authentik incluye por defecto (scope `profile`) claims como `name` o `preferred_username`; en versiones recientes el mapping por defecto de `profile` ya añade `groups`, pero conviene no asumirlo y comprobarlo explícitamente (paso 6) o crear tu propio mapping para tener control total sobre el formato:

1. **Customization → Property Mappings → Create → Scope Mapping**.
2. Nombre: `Capataz: groups` (o el que prefieras, es solo descriptivo).
3. **Scope name**: `groups`.
4. **Expression**:
   ```python
   return {
       "groups": [group.name for group in request.user.ak_groups.all()],
   }
   ```
5. Guarda. Este mapping se asocia al provider en el paso 3.

Si tu versión de Authentik ya expone `groups` con el mapping por defecto de `profile`, puedes omitir este paso — verifícalo en el paso 6 y añade el mapping propio solo si falta.

## 3. Crear el Provider OAuth2/OpenID

En **Applications → Providers → Create → OAuth2/OpenID Provider**:

| Campo | Valor recomendado | Motivo |
|---|---|---|
| Name | `Capataz` | Identifica el provider en la UI de Authentik. |
| Authorization flow | `default-provider-authorization-explicit-consent` (o `-implicit-consent` si prefieres saltar la pantalla de consentimiento en un homelab de un solo usuario) | Flujo estándar de Authentik. |
| Client type | **Public** | El frontend de Capataz es una SPA sin backend que pueda custodiar un `client_secret`; un client público fuerza PKCE (S256). |
| Client ID | déjalo autogenerado o fíjalo tú (p. ej. `capataz`) | Este valor es el que irá en `CAPATAZ_OIDC_AUDIENCE`. |
| Redirect URIs/Origins | `https://capataz.home.arpa/auth/callback` (strict) | Ruta fija que sirve `AuthCallbackPage.vue`; ajusta el host al dominio real de `frontend`. |
| Scopes | `openid`, `email`, `profile`, y el scope `groups` del paso 2 | `openid` es obligatorio; `email`/`profile` alimentan `Principal.email`; `groups` alimenta el RBAC. |
| Signing Key | selecciona un certificado RSA (p. ej. el `authentik Self-signed Certificate` que Authentik trae por defecto) | `OidcIdentityProvider` solo acepta tokens firmados en `RS256`; sin una Signing Key asignada, un client público no puede recibir tokens firmados de forma verificable. |

Guarda el provider.

> **Importante:** añade **una entrada de Redirect URI por cada origen desde el que vayas a probar** — Authentik deriva de esa lista tanto la validación del `redirect_uri` del código de autorización como las cabeceras CORS (`Access-Control-Allow-Origin`) que devuelve en `.well-known/openid-configuration` y `/application/o/token/`. Si pruebas desde `http://localhost:8090` además del dominio real, añade también `http://localhost:8090/auth/callback`, o el navegador bloqueará el `fetch()` de discovery con un error de CORS aunque el resto de la configuración sea correcta.

## 4. Crear la Application

En **Applications → Applications → Create**:

- Name: `Capataz`.
- Slug: `capataz` — este slug forma el issuer: `https://authentik.home.arpa/application/o/capataz/`.
- Provider: el que creaste en el paso 3.
- (Opcional) restringe la visibilidad de la aplicación en el launcher de Authentik a los tres grupos RBAC si no quieres que aparezca para todo el directorio.

## 5. Configurar las variables de entorno de Capataz

En `.env` (o las variables de `docker-compose.yml`):

```bash
CAPATAZ_AUTH_MODE=oidc
CAPATAZ_OIDC_ISSUER=https://authentik.home.arpa/application/o/capataz/
CAPATAZ_OIDC_AUDIENCE=<Client ID del paso 3>
CAPATAZ_OIDC_JWKS_URI=          # déjalo vacío: se descubre solo desde el issuer
CAPATAZ_OIDC_GROUPS_CLAIM=groups
```

`CAPATAZ_OIDC_ISSUER` debe coincidir carácter a carácter con el `iss` que emitan los tokens de Authentik (incluida la barra final) — cópialo del discovery document (paso 6), no lo escribas a mano.

Reinicia `api` para que `Settings`/`main.py` reconstruyan `app.state.identity_provider` con el nuevo modo (`docker compose up -d --force-recreate api`).

## 6. Verificar la integración

1. Comprueba el discovery document:
   ```bash
   curl -s https://authentik.home.arpa/application/o/capataz/.well-known/openid-configuration | jq .issuer,.jwks_uri
   ```
   El campo `issuer` debe ser exactamente el valor que pusiste en `CAPATAZ_OIDC_ISSUER`.
2. Obtén un `access_token` real completando el flujo Authorization Code + PKCE (con `curl`/Postman, o con la herramienta de "Test" de la aplicación en Authentik) y decodifícalo (p. ej. en [jwt.io](https://jwt.io) o `uv run python -c "import jwt; print(jwt.get_unverified_claims(...))"` desde `api/`) para confirmar que el payload incluye `"groups": ["capataz-..."]` y `"aud": "<client id>"`.
3. Llama a la API con ese token:
   ```bash
   curl -s -H "Authorization: Bearer <access_token>" https://capataz.home.arpa/api/v1/auth/me
   ```
   Debe devolver el `subject`, `email` y `groups` esperados. Un `401` con `AuthorizationError` en los logs de `api` casi siempre significa `iss`/`aud` desalineados o que el claim `groups` no llegó al access token (revisa el paso 2).

## 7. Configurar el login en el frontend

`CAPATAZ_FRONTEND_OIDC_*` se renderiza en `config.js` en tiempo de arranque del contenedor
(`frontend/nginx/40-render-runtime-config.sh`, ver [ADR 007](adr/007-runtime-frontend-config.es.md))
— ya no se hornea en el build de Vite, así que basta con la variable de entorno del contenedor, sin
`--build-arg` ni reconstruir la imagen:

```bash
# .env (usado por docker-compose.yml environment: del servicio frontend)
CAPATAZ_FRONTEND_OIDC_ISSUER=https://authentik.home.arpa/application/o/capataz/
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=<el mismo Client ID del paso 3 / CAPATAZ_OIDC_AUDIENCE>
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email groups
```

```bash
docker compose up -d --force-recreate frontend
```

Con `CAPATAZ_FRONTEND_OIDC_ISSUER`/`CAPATAZ_FRONTEND_OIDC_CLIENT_ID` vacíos (el valor por defecto), el frontend sigue sirviendo el modo `dev_mock` sin cambios — no hace falta tocar nada si no vas a usar OIDC todavía.

Flujo resultante para el usuario: entra a `https://capataz.home.arpa/`, el guard de rutas (`frontend/src/router/index.ts`) detecta que no hay sesión y navega a `/login`, que redirige de inmediato al `authorization_endpoint` de Authentik; tras autenticarse vuelve a `/auth/callback`, que intercambia el `code` por tokens (PKCE, sin `client_secret`), llama a `GET /api/v1/auth/me` para poblar el store de sesión y navega a la ruta que el usuario pedía originalmente. "Cerrar sesión" en el menú de cuenta limpia la sesión local y, si Authentik expone `end_session_endpoint`, hace logout RP-initiated también allí.

## 8. Personalizar las páginas de login/logout/cambio de contraseña al estilo de Capataz

El ejecutor de flujos de Authentik (login, logout, recuperación de contraseña, etc.) se
personaliza desde una **Brand de Authentik**, no con HTML por página — no hay override de
plantilla por flujo en la UI de administración estándar. Todo lo de abajo se configura en
**System → Brands → \<tu brand\>** (crea una brand no-default si aún no tienes una; se
aplica al dominio o dominios que le asignes, p. ej. `authentik.home.arpa`).

- **Branding title / Logo / Favicon**: campos simples bajo **Branding**. Sube
  `frontend/public/favicon.svg` tal cual (es un SVG con color propio, no depende de
  `currentColor`, así que se ve correctamente tanto de logo como de favicon sin retoques)
  y pon el título a `Capataz`.
- **Custom CSS**: campo de texto libre en la misma sección **Branding**. Authentik lo
  inyecta en el **shadow root** de cada componente del ejecutor de flujos, y cascada a
  través de `:root, :host` — así que sobrescribir custom properties CSS (`--ak-*`, y los
  tokens PatternFly `--pf-global--*` subyacentes) cambia colores, bordes, radios, etc. en
  todo el login/logout/recuperación sin necesidad de conocer el marcado interno de
  PatternFly.
- **Default flow background**: también en **Branding**, se aplica a todos los flujos que
  usen esta brand salvo que un flujo concreto lo sobrescriba (**Flows & Stages → Flows →
  \<flujo\> → Appearance settings → Background**, que también permite elegir layout:
  `stacked`, `content_left`, `content_right`, `sidebar_left`, `sidebar_right`).

`docs/assets/authentik-custom.css` en este repo es un Custom CSS listo para pegar,
construido a partir de los propios tokens de tema de Capataz
(`frontend/src/styles/quasar-variables.sass` y el bloque de tema oscuro de
`frontend/src/styles/app.scss` — el aspecto por defecto de Capataz): fondo oscuro
(`#101618`), paneles planos con borde en vez de la sombra por defecto de PatternFly,
acento teal (`#64aab0`) para acciones primarias, y el naranja "hard-hat" de marca
(`#ff6600`) reservado para hover/énfasis, igual que `--color-brand` en el frontend. Para
aplicarlo:

1. **System → Brands → \<tu brand\> → Branding → Custom CSS** → pega el contenido
   completo de `docs/assets/authentik-custom.css` → Update.
2. Sube `frontend/public/favicon.svg` como **Logo** y como **Favicon**.
3. Recarga `https://authentik.home.arpa/if/flow/default-authentication-flow/` (o el slug
   de tu flujo de autenticación configurado) y compáralo con el propio `/login` de
   Capataz.

El CSS solo apunta a custom properties más un par de selectores de clase PatternFly de
bajo riesgo (`.pf-c-login__main`, `.pf-c-card`, `.pf-c-button.pf-m-primary`) — el propio
archivo documenta qué parte quitar primero si una futura versión de authentik/PatternFly
deja de matchear esas clases. No existe una forma soportada de reemplazar la propia
estructura HTML del ejecutor de flujos (requeriría parchear el build del frontend de
authentik); el enfoque basado en variables de arriba es la superficie de personalización
prevista.

## Problemas frecuentes

- **Error de CORS en consola** (`No 'Access-Control-Allow-Origin' header is present`) al cargar `.well-known/openid-configuration` o al intercambiar el código por el token: casi siempre significa que el origen exacto desde el que estás probando (protocolo+host+puerto, p. ej. `http://localhost:8090`) no tiene su propio Redirect URI dado de alta en el provider (paso 3) — Authentik deriva el `Access-Control-Allow-Origin` de esa lista, no basta con que el dominio "real" de producción esté registrado. Añade `http://localhost:8090/auth/callback` (o el origen que uses) como Redirect URI adicional y reintenta.

- **`Unexpected token '$'...` (o cualquier basura no-JSON) al volver del callback**, con un `access_token`/`id_token` cuya cabecera dice `"typ":"JWE"` en vez de `"typ":"JWT"`: el provider tiene un **Encryption Certificate** asignado en Authentik, así que emite tokens cifrados en vez de firmados en claro (JWS/RS256). Ni el frontend (`decodeJwtPayload` para el `nonce`) ni el backend (`auth-middleware`) saben descifrar JWE. Quita el certificado de cifrado del provider (**Applications → Providers → capataz → Encryption Certificate → `---------`**) y guarda.

- **`Invalid OIDC access token` (403) en `/api/v1/auth/me`, y en los logs de `api` `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`**: Authentik (o el proxy delante) usa un certificado firmado por una **CA interna** del homelab, que el navegador ya conoce pero el contenedor `api` no — es una imagen Python mínima con solo las CAs públicas estándar. Arréglalo confiando en tu CA desde Capataz, **nunca** desactivando la verificación TLS:
  ```bash
  make trust-ca CA_URL=http://pi-dns.home.arpa/ca.crt   # descarga tu CA y genera certs/ca-bundle.pem
  ```
  Añade a `.env`:
  ```bash
  SSL_CERT_FILE=/run/ca-certs/ca-bundle.pem
  ```
  y reinicia `api`/`runner` (`docker compose up -d --force-recreate api runner`). `certs/ca-bundle.pem` combina el bundle público del sistema con tu CA — no sustituye la confianza en CAs públicas, solo la amplía. Si regeneras el certificado de servicio de tu CA (rutina, no afecta a la CA en sí) no hace falta rehacer nada aquí; solo si rotas la CA raíz habría que repetir `make trust-ca`.

## Notas de seguridad

- No pongas `CAPATAZ_OIDC_AUDIENCE` vacío en producción: sin él, `OidcProvider` acepta cualquier token válido emitido por el issuer para **cualquier** client, no solo para Capataz (mismo comportamiento documentado para Cognito en el ADR 004, sección "Consecuencias").
- No hace falta ningún secreto de Docker nuevo para OIDC: al ser un client público, no hay `client_secret` que gestionar en el lado de Capataz — la revocación de acceso se hace quitando al usuario del grupo de Authentik correspondiente.
- Si migras de Cognito a OIDC en un entorno ya en producción, cambia `CAPATAZ_AUTH_MODE` en una ventana de mantenimiento: todas las sesiones con tokens Cognito dejan de validar en cuanto el pod de `api` se reinicia con el nuevo modo.
- Limitación conocida ya resuelta: el antiguo stream de eventos de una ejecución (`GET /executions/{id}/events/stream`) usaba `EventSource`, que no permite adjuntar cabeceras `Authorization`, así que nunca autenticaba correctamente fuera de `dev_mock`. El endpoint se ha retirado (ver `docs/12-roadmap.md` ítem #4 histórico); la página de ejecución usa sondeo periódico autenticado (`GET /executions/{id}` + `GET /executions/{id}/events` cada 3s) en su lugar.
