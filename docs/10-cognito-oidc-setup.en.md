# Setting up AWS Cognito as an OIDC provider for Capataz

*Language: **English** · [Español](10-cognito-oidc-setup.es.md)*

Step-by-step guide to register Capataz in an AWS Cognito **User Pool** and enable `CAPATAZ_AUTH_MODE=cognito`. It's the counterpart to [`docs/09-authentik-oidc-setup.md`](09-authentik-oidc-setup.en.md) — the same Authorization Code + PKCE flow in the frontend, the same `/api/v1/auth/me` to populate the session store — but with Cognito's own quirks that don't apply to a generic OIDC issuer.

## How it fits into Capataz

Since auth-middleware 0.6.0 there's no dedicated `CognitoProvider`: as far as `OidcProvider` is concerned, a Cognito User Pool is just another OIDC issuer. `CognitoIdentityProvider` (`api/src/capataz_api/adapters/inbound/auth.py`) builds an `OidcProvider` pointing at Cognito's **native issuer**:

```
https://cognito-idp.{CAPATAZ_COGNITO_REGION}.amazonaws.com/{CAPATAZ_COGNITO_USER_POOL_ID}
```

(no trailing slash — unlike Authentik's issuer, which does have one) and passes it a `CognitoGroupsProvider` as `groups_provider`. This is necessary because, unlike Authentik, Cognito's groups claim (`cognito:groups`) **normally only appears in the ID token, not the access token** — and the `Authorization: Bearer` that the API validates is always the access token. `CognitoGroupsProvider` still tries to read `cognito:groups` from the token itself (in case your configuration does include it) and, if it's not there, falls back to a heuristic based on a single custom scope in `resourceServer/scopeName` format — which is **not** the same as real group membership. We'll verify this with a real token in step 6; if needed, step 3 explains how to force the claim onto the access token with a Lambda trigger.

> **Frontend:** the same generic client you already use with Authentik (`frontend/src/api/oidc.ts`, Authorization Code + PKCE) works as-is for Cognito — Cognito's Hosted UI exposes a standard `.well-known/openid-configuration` under the native issuer. Only the `CAPATAZ_FRONTEND_OIDC_*` values in `config.js` change, not the code.

## Prerequisites

- An AWS account with permissions to create/manage Cognito resources.
- Capataz's three RBAC roles: `capataz-viewer` < `capataz-operator` < `capataz-admin` (hierarchical only within Capataz — in Cognito they're independent groups, same as Authentik: a user only needs to belong to the group matching their highest privilege).
- Outbound connectivity from `api`/`runner` to `cognito-idp.{region}.amazonaws.com` — unlike Authentik, Cognito uses certificates from a standard public CA, so you should **not** need `make trust-ca`/`SSL_CERT_FILE` for this (that guide was specific to the homelab's internal CA).

## 1. Create the User Pool

**Amazon Cognito → User pools → Create user pool**:

- **Sign-in options**: `Email` (Capataz uses the email claim for `Principal.email`; you can also add `Username` if you want, but it's not required).
- **MFA**: optional to start testing; consider making it mandatory in production.
- **Required attributes**: `email` at minimum.
- Save the **User Pool ID** (format `{region}_XXXXXXXXX`) and the **region** — these are `CAPATAZ_COGNITO_USER_POOL_ID` and `CAPATAZ_COGNITO_REGION`.

You don't need the "initial app client" the wizard offers at the end — we create that separately in step 4, with the specific options a PKCE SPA needs.

## 2. Create the RBAC groups in Cognito

**User Pool → Users and groups → Groups → Create group** — create exactly these three (literal name, case-sensitive, this is what travels in `cognito:groups`):

- `capataz-viewer`
- `capataz-operator`
- `capataz-admin`

Add each user to **exactly one** group, matching their highest privilege — same as Authentik, the hierarchy is enforced by the Capataz backend (`api/src/capataz_api/application/policies/rbac.py::has_role`), no need to duplicate memberships.

## 3. If the `cognito:groups` claim doesn't make it into the access token

Check this first in step 6 before doing anything here — many configurations resolve it with step 4 alone and this isn't needed. If the real `access_token` doesn't carry `cognito:groups` (Cognito's default behavior), the supported way to add it is a **Pre Token Generation Lambda trigger**:

1. **User Pool → General settings → Triggers** (or **Extensions → Lambda triggers** depending on the console version) → create/assign a **Pre token generation** trigger.
2. The Lambda function must return the claim in `claimsToAddOrOverride` for the `accessToken` (not just the `idToken`) — trigger event version V2\_0, which is what lets you tell the ID token and access token apart:
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
3. Save and test again — the new `access_token` should now include `cognito:groups`.

If you'd rather not touch Lambdas, the alternative is to accept RBAC depending on `CognitoGroupsProvider`'s single-scope heuristic (less flexible: one "group" per client via a Cognito Resource Server/custom scope) — not recommended except for a very simple use case.

## 4. Create the Domain (Hosted UI)

**User Pool → App integration → Domain**:

- **Cognito domain**: pick a prefix (`https://<prefix>.auth.{region}.amazoncognito.com`), or set up your own domain if you already have one with a certificate.

Without this there's no Hosted UI — the native issuer's discovery document (step 6) will still exist, but its `authorization_endpoint`/`token_endpoint` point precisely at this domain, so without it login has nowhere to redirect to.

## 5. Create the App Client

**User Pool → App integration → App clients → Create app client**:

| Field | Recommended value | Why |
|---|---|---|
| App type | **Public client** | Capataz's SPA can't safeguard a `client_secret`; a public client in Cognito uses PKCE automatically in the code exchange, no need to enable it separately. |
| Client secret | **Don't generate a client secret** | Consistent with "Public client". |
| Authentication flows | Doesn't matter for this flow (these are for `InitiateAuth`, Cognito's native API) — no need to check any. | Capataz uses Hosted UI + OAuth2, not the `InitiateAuth`/`RespondToAuthChallenge` API. |
| Allowed OAuth Flows | **Authorization code grant** (leave "Implicit grant" unchecked) | PKCE only applies to the authorization code flow. |
| Allowed OAuth Scopes | `openid`, `email`, `profile` | Cognito doesn't have a `groups` scope like Authentik — the groups claim arrives (or doesn't) per step 3, regardless of the requested scope. **Don't** include `groups` here: unlike Authentik, an unrecognized scope can make Cognito reject the authorization request. |
| Callback URLs | `http://localhost:8090/auth/callback` (and the real domain once you have it) | Fixed path served by `AuthCallbackPage.vue` — add one entry per origin you test from. |
| Sign-out URLs | same origin, e.g. `http://localhost:8090/` | See the logout note below — Cognito uses it differently from Authentik. |

Save the **Client ID** — this is `CAPATAZ_COGNITO_APP_CLIENT_ID` / `CAPATAZ_FRONTEND_OIDC_CLIENT_ID`.

> **Important:** "Allowed OAuth Scopes" is **per App Client**, not per User Pool — the discovery document (`.well-known/openid-configuration`) listing `profile` in `scopes_supported` only means the *pool* supports it in general, not that your specific client has it enabled. If `CAPATAZ_FRONTEND_OIDC_SCOPE` requests a scope the client doesn't have checked, `/oauth2/authorize` redirects to your `redirect_uri` with `error=invalid_request&error_description=invalid_scope` — without saying which scope is the problem. Check by testing one at a time if this happens to you:
> ```bash
> curl -sS -o /dev/null -w "%{redirect_url}\n" "https://<hosted-ui-domain>/oauth2/authorize?client_id=<client_id>&response_type=code&scope=openid+profile&redirect_uri=<redirect_uri>&state=test&nonce=test&code_challenge=x&code_challenge_method=S256"
> ```
> A redirect to `/login` means those scopes are allowed; a redirect back to your `redirect_uri` with `error=invalid_request` points at the scope that's the odd one out.

## 6. Configure Capataz's environment variables

Backend, in `.env`:

```bash
CAPATAZ_AUTH_MODE=cognito
CAPATAZ_COGNITO_REGION=<your region, e.g. eu-west-1>
CAPATAZ_COGNITO_USER_POOL_ID=<User Pool ID from step 1>
CAPATAZ_COGNITO_APP_CLIENT_ID=<Client ID from step 5>
```

Restart `api` so it rebuilds `app.state.identity_provider` (`docker compose up -d --force-recreate api`).

Frontend — same as with Authentik, it's runtime container config (see
[ADR 007](adr/007-runtime-frontend-config.en.md)):

```bash
CAPATAZ_FRONTEND_USE_MSW=false
CAPATAZ_FRONTEND_OIDC_ISSUER=https://cognito-idp.<region>.amazonaws.com/<user_pool_id>   # NO trailing slash
CAPATAZ_FRONTEND_OIDC_CLIENT_ID=<the same Client ID from step 5>
CAPATAZ_FRONTEND_OIDC_SCOPE=openid profile email
```

```bash
docker compose up -d --force-recreate frontend
```

## 7. Verify the integration

1. Discovery document (native issuer, not the Hosted UI domain):
   ```bash
   curl -s https://cognito-idp.<region>.amazonaws.com/<user_pool_id>/.well-known/openid-configuration | jq .issuer,.authorization_endpoint,.token_endpoint
   ```
   `issuer` must match character-for-character what `CognitoIdentityProvider` builds; `authorization_endpoint`/`token_endpoint` should point at the Hosted UI domain from step 4, not the native issuer.
2. Log in from the Capataz UI and, if something fails, check Network → the `POST` request to `token_endpoint` (same procedure we used with Authentik). If you get an `access_token`, decode it (e.g. at [jwt.io](https://jwt.io), without verifying the signature) and confirm:
   - `"iss"` = the exact native issuer.
   - `"client_id"` (Cognito uses this claim, not always `"aud"`, to identify the client in access tokens) = your Client ID.
   - `"cognito:groups"` present with your group — if it's missing, go back to step 3.
3. Call the API with that token:
   ```bash
   curl -s -H "Authorization: Bearer <access_token>" http://localhost:8090/api/v1/auth/me
   ```
   It should return `subject`/`email`/`groups`. A 403 with `Invalid Cognito access token` in `api`'s logs is almost always a missing `cognito:groups` (empty RBAC, not the same as a signature failure) or a region/User Pool ID mismatch in the issuer.

## 8. Brand the Managed Login pages to match Capataz

Only applies if the Hosted UI domain uses **Managed Login v2** (Cognito's newer style editor), not the classic Hosted UI:

```bash
aws cognito-idp describe-user-pool-domain --domain <prefix-from-step-4> --region <region> --query 'DomainDescription.ManagedLoginVersion'
```

If it returns `2`, keep reading. If it returns `1` (or the field is absent), that's the classic Hosted UI — it only supports a single logo (PNG, uploaded via the deprecated `SetUICustomization`) and a CSS block scoped to fixed class names like `.background-customizable`/`.submitButton-customizable`; no visual editor and none of the fine-grained control below.

`docs/assets/cognito-managed-login-branding.py` in this repo applies Capataz's theme to an existing `ManagedLoginBranding` via the API — it's the Cognito equivalent of `docs/assets/authentik-custom.css`, but since Managed Login doesn't accept free-form CSS (the style is a structured JSON object per component: `form`, `primaryButton`, `pageHeader`, `pageBackground`, etc., plus base64 image assets per category), instead of a paste-in file it's a script that builds that JSON from the same tokens as `frontend/src/styles/app.scss` (`:root` block = dark theme, `body.body--light` = light theme) and applies it with `update-managed-login-branding`:

```bash
# print the payload only (dry run)
python3 docs/assets/cognito-managed-login-branding.py \
  --user-pool-id <CAPATAZ_COGNITO_USER_POOL_ID> --client-id <CAPATAZ_COGNITO_APP_CLIENT_ID> --region <region>

# actually apply it
python3 docs/assets/cognito-managed-login-branding.py \
  --user-pool-id <CAPATAZ_COGNITO_USER_POOL_ID> --client-id <CAPATAZ_COGNITO_APP_CLIENT_ID> --region <region> --apply
```

It only needs the AWS CLI configured with credentials that can call `cognito-idp:DescribeManagedLoginBrandingByClient`/`UpdateManagedLoginBranding` — no `boto3`, no repo dependencies. It reuses `frontend/public/favicon.svg` as the logo (form + header) and favicon — the script sanitizes an in-memory copy by stripping `role`/`aria-label` from the root `<svg>` before uploading, because Cognito's SVG sanitizer rejects them (`element [svg#role|aria-label] is not allowed`); the repo's `favicon.svg` itself is left untouched. It maps:

- Page background, form card, header and footer → `--color-bg`/`--color-surface`/`--color-border` (dark and light).
- Primary button → `--color-primary` by default, `--color-brand` (`#ff6600`) on hover/active — same convention as `authentik-custom.css`.
- `categories.global.colorSchemeMode` → `DYNAMIC`, so Managed Login follows the browser's `prefers-color-scheme` instead of locking to one theme.
- Corner radii: `12px` on the card (`--radius-lg`), `6px` on buttons (`--radius-sm`).

Heads-up if you touch the script or the JSON by hand: `categories.form.displayGraphics` controls Cognito's default decorative triangle/gradient motif — it's independent of `components.form.logo`, and if left `true` it paints over `components.pageBackground.color` even when that's configured correctly (that's how this was caught: Capataz's flat background didn't show up until this was set to `false`). The script already disables it.

Known limitation: Managed Login's `pageHeader`/`pageFooter` only accept a logo image, there's no text field for a title — so "turn on the header with Capataz" in practice means showing the `favicon.svg` icon (the same orange hard-hat mark used elsewhere in the app), not a text wordmark. If you ever want the literal name "Capataz" visible there, you'd need an SVG with the text baked in and to add its category (`PAGE_HEADER_LOGO`) to the script — not implemented yet.

Verification: open the Hosted UI login URL directly (no need for Capataz's own frontend):

```
https://<hosted-ui-domain>/login?client_id=<CAPATAZ_COGNITO_APP_CLIENT_ID>&response_type=code&scope=openid+profile+email&redirect_uri=<a-registered-redirect-uri>
```

**Managed Login is served behind CloudFront** — after applying, if you still see the previous style (or Cognito's default decorative gradient) in the browser, hard-reload (`Ctrl+Shift+R`) before assuming it didn't take; compare against what `aws cognito-idp describe-managed-login-branding` returns (or a direct `curl` of the login URL, which does reflect server state immediately) to rule out browser caching.

## Common issues

- **CORS when `fetch`-ing the discovery document or exchanging the code for the token**: verified live against the `Capataz` user pool (`eu-west-1_T1JkF6VNE`) — no proxy or workaround needed. The discovery document (`cognito-idp.<region>.amazonaws.com/<pool>/.well-known/openid-configuration`) responds with `access-control-allow-origin: *`. The Hosted UI domain's `token_endpoint` (`/oauth2/token`) does implement CORS correctly: both the `OPTIONS` preflight and the real `POST` response return `access-control-allow-origin` set to the **exact request Origin** plus `access-control-allow-credentials: true`. Unlike Authentik, this is **not scoped to the Callback URLs registered on the App Client** — Cognito reflects back whatever Origin you send (confirmed with a made-up origin, which it accepted too), so if you hit a CORS error here it's not a Cognito configuration problem: check that the browser's own `fetch`/`XMLHttpRequest` call is well-formed (headers, `Content-Type`, no unnecessary `credentials: 'include'`) before suspecting the server side.
- **Logout returns "Invalid request. Please check your input and try again." and redirects to `/login` instead of logging out**: found and fixed live (2026-08-19) testing against the `Capataz` user pool. With **Managed Login v2** the discovery document **does** include `end_session_endpoint` (`https://<hosted-ui-domain>/logout`) — contrary to what this note used to say — but that endpoint **doesn't implement standard RP-initiated logout**: if you send it `id_token_hint` (with or without `post_logout_redirect_uri`/`client_id`), it rejects the request and bounces to `/login` with "Invalid request", carrying those same params along in the query string (confirmed with `curl` against the live endpoint). It only accepts its own proprietary `client_id` + `logout_uri` pair — no `id_token_hint`. `oidc.ts::logout()` now distinguishes this: `isCognitoIssuer()` detects the `cognito-idp.<region>.amazonaws.com` issuer and uses `logout_uri` instead of `id_token_hint`/`post_logout_redirect_uri`; against any other IdP (Authentik, Keycloak...) it still uses standard RP-initiated logout. If you hit this error, double-check the exact origin (`window.location.origin`, no trailing slash) is in the App Client's **Sign-out URLs** — Cognito requires an exact match there too.
- **RBAC empty even though the user is in a group**: check step 3 — that's the most likely cause, not a Capataz configuration issue.

## Security notes

- Don't leave `CAPATAZ_COGNITO_APP_CLIENT_ID` empty in production — without it, `OidcProvider` doesn't validate the token's audience/client claim, same reasoning as `CAPATAZ_OIDC_AUDIENCE` for Authentik (see ADR 004, "Consequences" section).
- No new Docker secret is needed for this mode either: public client, no `client_secret` to manage in Capataz.
- Same known limitation as with Authentik: the execution SSE stream (`frontend/src/api/sse.ts`) doesn't carry `Authorization` outside `dev_mock` — see `docs/09-authentik-oidc-setup.md#security-notes` for details, it applies here too.
