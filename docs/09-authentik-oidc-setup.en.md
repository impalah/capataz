# Configuring Authentik as an OIDC provider for Capataz

*Language: **English** · [Español](09-authentik-oidc-setup.es.md)*

Step-by-step guide to register Capataz as an OIDC application in [Authentik](https://goauthentik.io/) and enable `CAPATAZ_AUTH_MODE=oidc` (`OidcIdentityProvider`, see [ADR 004](adr/004-auth-middleware-adoption.en.md)). Authentik is just one example of a standard issuer — the same conceptual procedure applies to Keycloak, Auth0, or Okta, since `OidcIdentityProvider` doesn't assume anything provider-specific.

## How it fits into Capataz

`OidcIdentityProvider` verifies the `access_token` received in `Authorization: Bearer <token>` against the configured OIDC issuer:

1. It discovers the JWKS from `{CAPATAZ_OIDC_ISSUER}/.well-known/openid-configuration` (unless you set `CAPATAZ_OIDC_JWKS_URI` explicitly).
2. It verifies the signature (`RS256` only) and the `iss`/`aud` claims (`aud` must match `CAPATAZ_OIDC_AUDIENCE`, the `client_id`).
3. It reads the RBAC role directly from the `CAPATAZ_OIDC_GROUPS_CLAIM` claim (default `groups`) **on the `access_token` itself** — it does not make an extra call to `/userinfo` or use an external `GroupsProvider` the way Cognito does.

So the key requirement on the Authentik side isn't just "create an OIDC application" — it's making sure the `access_token` that Authentik issues (not just the `id_token`) includes the `groups` claim with the exact group names `capataz-viewer` / `capataz-operator` / `capataz-admin`.

> **Frontend:** the browser login (`frontend/src/api/oidc.ts`) performs a generic Authorization Code + PKCE flow against the `OIDC_ISSUER`/`OIDC_CLIENT_ID` from `config.js` (rendered from `CAPATAZ_FRONTEND_OIDC_ISSUER`/`CAPATAZ_FRONTEND_OIDC_CLIENT_ID`, see [ADR 007](adr/007-runtime-frontend-config.en.md)) and attaches the `access_token` as `Authorization: Bearer` on every call (`frontend/src/api/client.ts`); it's only enabled when `CAPATAZ_FRONTEND_USE_MSW=false`. The callback lives at the `/auth/callback` route (`frontend/src/pages/AuthCallbackPage.vue`) — that's the URL you need to register as the Redirect URI in step 3.

## Prerequisites

- An Authentik instance with admin access (`https://authentik.home.arpa` in the examples below).
- Capataz's three RBAC roles as defined in `docs/02-contracts.md`: `capataz-viewer` < `capataz-operator` < `capataz-admin` (hierarchical only within Capataz — in Authentik they're independent groups, see the note in step 1).
- Outbound connectivity from the `api` container to Authentik (for the discovery document and the JWKS) — if Authentik is on `.home.arpa`, this is already covered by `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` for health checks, but the OIDC verification itself does not go through those SSRF defenses (they only apply to service/health URLs, not token validation).
- If your Authentik (or Portainer/Grafana/Loki/Prometheus) sits behind a certificate signed by an **internal CA** (not public) from the homelab, `api`/`runner` need to explicitly trust it — see "Common issues" below (`make trust-ca`). Without this, the request to the discovery document fails with `CERTIFICATE_VERIFY_FAILED` even though the browser doesn't complain (the browser already trusts your CA; the Python container doesn't, by default).

## 1. Create the RBAC groups in Authentik

Under **Directory → Groups**, create exactly these three groups (the literal name is the value that travels in the `groups` claim, case-sensitive):

- `capataz-viewer`
- `capataz-operator`
- `capataz-admin`

Add each user to **a single** group, matching their highest privilege. The hierarchy (admin implies operator implies viewer) is enforced by the Capataz backend (`api/src/capataz_api/application/policies/rbac.py::has_role`), which checks membership against a set of groups — you **don't** need to also add an admin to `capataz-operator`/`capataz-viewer` in Authentik.

## 2. Expose the `groups` claim in the access token

Authentik includes claims like `name` or `preferred_username` by default (via the `profile` scope); in recent versions the default `profile` mapping already adds `groups`, but it's worth not assuming this and checking explicitly (step 6), or creating your own mapping for full control over the format:

1. **Customization → Property Mappings → Create → Scope Mapping**.
2. Name: `Capataz: groups` (or whatever you prefer, it's just descriptive).
3. **Scope name**: `groups`.
4. **Expression**:
   ```python
   return {
       "groups": [group.name for group in request.user.ak_groups.all()],
   }
   ```
5. Save. This mapping gets attached to the provider in step 3.

If your version of Authentik already exposes `groups` via the default `profile` mapping, you can skip this step — verify it in step 6 and add your own mapping only if it's missing.

## 3. Create the OAuth2/OpenID Provider

Under **Applications → Providers → Create → OAuth2/OpenID Provider**:

| Field | Recommended value | Why |
|---|---|---|
| Name | `Capataz` | Identifies the provider in the Authentik UI. |
| Authorization flow | `default-provider-authorization-explicit-consent` (or `-implicit-consent` if you'd rather skip the consent screen in a single-user homelab) | Standard Authentik flow. |
| Client type | **Public** | The Capataz frontend is an SPA with no backend that could hold a `client_secret`; a public client forces PKCE (S256). |
| Client ID | leave it autogenerated or set it yourself (e.g. `capataz`) | This value goes into `CAPATAZ_OIDC_AUDIENCE`. |
| Redirect URIs/Origins | `https://capataz.home.arpa/auth/callback` (strict) | Fixed path served by `AuthCallbackPage.vue`; adjust the host to `frontend`'s real domain. |
| Scopes | `openid`, `email`, `profile`, and the `groups` scope from step 2 | `openid` is mandatory; `email`/`profile` feed `Principal.email`; `groups` feeds RBAC. |
| Signing Key | select an RSA certificate (e.g. the `authentik Self-signed Certificate` Authentik ships by default) | `OidcIdentityProvider` only accepts `RS256`-signed tokens; without a Signing Key assigned, a public client can't receive verifiably signed tokens. |

Save the provider.

> **Important:** add **one Redirect URI entry per origin you'll test from** — Authentik derives from that list both the authorization code's `redirect_uri` validation and the CORS headers (`Access-Control-Allow-Origin`) it returns on `.well-known/openid-configuration` and `/application/o/token/`. If you're testing from `http://localhost:8090` in addition to the real domain, also add `http://localhost:8090/auth/callback`, or the browser will block the discovery `fetch()` with a CORS error even if everything else is configured correctly.

## 4. Create the Application

Under **Applications → Applications → Create**:

- Name: `Capataz`.
- Slug: `capataz` — this slug forms the issuer: `https://authentik.home.arpa/application/o/capataz/`.
- Provider: the one you created in step 3.
- (Optional) restrict the application's visibility in the Authentik launcher to the three RBAC groups if you don't want it showing up for the whole directory.

## 5. Configure Capataz's environment variables

In `.env` (or the `docker-compose.yml` variables):

```bash
CAPATAZ_AUTH_MODE=oidc
CAPATAZ_OIDC_ISSUER=https://authentik.home.arpa/application/o/capataz/
CAPATAZ_OIDC_AUDIENCE=<Client ID from step 3>
CAPATAZ_OIDC_JWKS_URI=          # leave it empty: it's discovered from the issuer alone
CAPATAZ_OIDC_GROUPS_CLAIM=groups
```

`CAPATAZ_OIDC_ISSUER` must match character-for-character the `iss` that Authentik's tokens emit (including the trailing slash) — copy it from the discovery document (step 6), don't type it by hand.

Restart `api` so `Settings`/`main.py` rebuild `app.state.identity_provider` with the new mode (`docker compose up -d --force-recreate api`).

## 6. Verify the integration

1. Check the discovery document:
   ```bash
   curl -s https://authentik.home.arpa/application/o/capataz/.well-known/openid-configuration | jq .issuer,.jwks_uri
   ```
   The `issuer` field must be exactly the value you set in `CAPATAZ_OIDC_ISSUER`.
2. Get a real `access_token` by completing the Authorization Code + PKCE flow (with `curl`/Postman, or with the application's "Test" tool in Authentik) and decode it (e.g. at [jwt.io](https://jwt.io) or with `uv run python -c "import jwt; print(jwt.get_unverified_claims(...))"` from `api/`) to confirm the payload includes `"groups": ["capataz-..."]` and `"aud": "<client id>"`.
3. Call the API with that token:
   ```bash
   curl -s -H "Authorization: Bearer <access_token>" https://capataz.home.arpa/api/v1/auth/me
   ```
   It should return the expected `subject`, `email`, and `groups`. A `401` with `AuthorizationError` in the `api` logs almost always means `iss`/`aud` are mismatched, or that the `groups` claim didn't make it into the access token (check step 2).

## 7. Configure frontend login

`CAPATAZ_FRONTEND_OIDC_*` is rendered into `config.js` at container startup
(`frontend/nginx/40-render-runtime-config.sh`, see [ADR 007](adr/007-runtime-frontend-config.en.md))
— it's no longer baked into the Vite build, so the container's environment variable is enough, no
`--build-arg` or image rebuild needed:

```bash
# .env (used by docker-compose.yml's environment: for the frontend service)
CAPATAZ_FRONTEND_OIDC_ISSUER=https://authentik.home.arpa/application/o/capataz/
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=<the same Client ID from step 3 / CAPATAZ_OIDC_AUDIENCE>
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email groups
```

```bash
docker compose up -d --force-recreate frontend
```

With `CAPATAZ_FRONTEND_OIDC_ISSUER`/`CAPATAZ_FRONTEND_OIDC_CLIENT_ID` empty (the default), the frontend keeps serving `dev_mock` mode unchanged — there's nothing to touch if you're not using OIDC yet.

Resulting user flow: they go to `https://capataz.home.arpa/`, the route guard (`frontend/src/router/index.ts`) detects there's no session and navigates to `/login`, which immediately redirects to Authentik's `authorization_endpoint`; after authenticating it returns to `/auth/callback`, which exchanges the `code` for tokens (PKCE, no `client_secret`), calls `GET /api/v1/auth/me` to populate the session store, and navigates to the route the user originally requested. "Log out" in the account menu clears the local session and, if Authentik exposes an `end_session_endpoint`, also performs RP-initiated logout there.

## Common issues

- **CORS error in the console** (`No 'Access-Control-Allow-Origin' header is present`) while loading `.well-known/openid-configuration` or exchanging the code for the token: this almost always means the exact origin you're testing from (protocol+host+port, e.g. `http://localhost:8090`) doesn't have its own Redirect URI registered on the provider (step 3) — Authentik derives `Access-Control-Allow-Origin` from that list, and it isn't enough for the "real" production domain to be registered. Add `http://localhost:8090/auth/callback` (or whichever origin you're using) as an additional Redirect URI and retry.

- **`Unexpected token '$'...` (or any non-JSON garbage) when returning from the callback**, with an `access_token`/`id_token` whose header says `"typ":"JWE"` instead of `"typ":"JWT"`: the provider has an **Encryption Certificate** assigned in Authentik, so it issues encrypted tokens instead of plain signed ones (JWS/RS256). Neither the frontend (`decodeJwtPayload` for the `nonce`) nor the backend (`auth-middleware`) knows how to decrypt JWE. Remove the encryption certificate from the provider (**Applications → Providers → capataz → Encryption Certificate → `---------`**) and save.

- **`Invalid OIDC access token` (403) on `/api/v1/auth/me`, with `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate` in the `api` logs**: Authentik (or the proxy in front of it) uses a certificate signed by an **internal** homelab CA, which the browser already knows about but the `api` container doesn't — it's a minimal Python image with only the standard public CAs. Fix it by trusting your CA from Capataz, **never** by disabling TLS verification:
  ```bash
  make trust-ca CA_URL=http://pi-dns.home.arpa/ca.crt   # downloads your CA and generates certs/ca-bundle.pem
  ```
  Add to `.env`:
  ```bash
  SSL_CERT_FILE=/run/ca-certs/ca-bundle.pem
  ```
  and restart `api`/`runner` (`docker compose up -d --force-recreate api runner`). `certs/ca-bundle.pem` combines the system's public bundle with your CA — it doesn't replace trust in public CAs, only extends it. If you regenerate your CA's service certificate (routine, doesn't affect the CA itself) there's nothing to redo here; only rotating the root CA requires repeating `make trust-ca`.

## Security notes

- Don't leave `CAPATAZ_OIDC_AUDIENCE` empty in production: without it, `OidcProvider` accepts any valid token issued by the issuer for **any** client, not just Capataz (same behavior documented for Cognito in ADR 004, "Consequences" section).
- No new Docker secret is needed for OIDC: being a public client, there's no `client_secret` to manage on Capataz's side — revoking access is done by removing the user from the corresponding Authentik group.
- If you migrate from Cognito to OIDC in an environment already in production, change `CAPATAZ_AUTH_MODE` during a maintenance window: all sessions with Cognito tokens stop validating as soon as the `api` pod restarts with the new mode.
- Known limitation, already resolved: the old execution event stream (`GET /executions/{id}/events/stream`) used `EventSource`, which cannot attach `Authorization` headers, so it never authenticated correctly outside `dev_mock`. The endpoint has been retired (see `docs/12-roadmap.md` item #4, historical); the execution page uses authenticated periodic polling (`GET /executions/{id}` + `GET /executions/{id}/events` every 3s) instead.
