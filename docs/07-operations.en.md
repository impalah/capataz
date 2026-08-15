# Operations

*Language: **English** · [Español](07-operations.es.md)*

## Compose Deployment

1. Copy `.env.example` to `.env`, fill in only non-sensitive values, and create the seven `secrets/` files following the README.
2. Protect the secrets: `chmod 600 secrets/*`; also restrict the directory (`chmod 700 secrets`).
3. Check the composition before starting: `docker compose config`.
4. Build and start: `make build && make up`.
5. Wait for `make ps`, apply `make migrate`, and load the catalog with `make seed-catalog` if it wasn't imported at startup.

The normal profile only publishes the frontend on `8080` and the API on `8000`. PostgreSQL and Redis stay on the `internal` network and are never published.

## Standalone Frontend Deployment (S3+CloudFront / Your Own Nginx)

`frontend/dist/` is a static artifact (hashed HTML/JS/CSS + `config.js`) that doesn't need
Docker or Nginx to exist — just a static file server. The configuration
(`API_BASE_URL`, `USE_MSW`, `OIDC_*`) is read at browser runtime from
`config.js`, not baked into the build (see
[ADR 007](adr/007-runtime-frontend-config.en.md)), so **a single build serves any
number of environments**: only `config.js` changes between them.

### 1. Build once

```bash
cd frontend
npm ci
make build-package   # generates dist/ + capataz-frontend-<version>.zip
```

The `config.js` included in that `dist/`/zip is the one committed at `frontend/public/config.js`
(local development defaults: `USE_MSW: true`, API at `http://localhost:8000/api/v1`). **It does not work
as-is in a real deployment** — it must always be replaced, see step 2.

### 2. Configure `config.js` per Environment

Before uploading/serving `dist/`, overwrite `dist/config.js` (or the already-deployed `config.js`, without
touching the rest of the artifact) with the environment's real values:

```js
window.__APP_CONFIG__ = {
  API_BASE_URL: 'https://api.yourdomain.com/api/v1', // or '/api/v1' if you're proxying, see 3b/4
  USE_MSW: false, // always false in any deployment reachable from outside your LAN
  OIDC_ISSUER: 'https://your-issuer/...',
  OIDC_CLIENT_ID: 'xxxxx',
  OIDC_SCOPE: 'openid profile email groups',
}
```

**`USE_MSW: true` enables `dev_mock` mode (no login) — see the security note at the end of
this section before deploying anything reachable from outside your trusted network.**

### 3. S3 + CloudFront

a. Upload the contents of `dist/` (already with its real `config.js`) to an S3 bucket, serving it via
   CloudFront with `index.html` as the *default root object* and as the *error document* for 403/404
   (necessary for Vue Router routes, e.g. `/services/x`, to work on page
   reload — equivalent to `default.conf`'s `try_files … /index.html`).
b. Cache differentiated by file type — this is the only thing really specific to a CDN:
   - `config.js`: `Cache-Control: no-store` (or a TTL of seconds at most). A CloudFront
     `invalidation` after redeploying it isn't enough on its own if the browser already cached it locally.
   - `assets/*` (JS/CSS with a hash in the filename): long, immutable cache
     (`public, max-age=31536000, immutable`) — a redeploy generates different filenames, so
     there's no risk of serving an old version.
   - `index.html`: short cache or `no-cache` (always revalidates), same as `config.js`.
c. The API needs to be reachable from the user's browser. Two options:
   - **Absolute URL + CORS** (simpler): `API_BASE_URL: 'https://api.yourdomain.com/api/v1'` in
     `config.js`, and add the CloudFront domain to `CAPATAZ_CORS_ORIGINS` in the API's `.env`.
     `Access-Control-Allow-Credentials` isn't needed: authentication goes through
     `Authorization: Bearer` (OIDC), never cookies.
   - **A second origin/behavior in CloudFront** for `/api/*` pointing at the API's origin,
     replicating what `location /api/` does in `default.conf`: then `config.js` can keep
     using `API_BASE_URL: '/api/v1'` (relative), without touching CORS.

### 4. Your Own Nginx (No Docker)

```bash
cp -r dist/* /path/to/nginx/webroot/
```

Replicate the `server{}` block from `frontend/nginx/default.conf`: `try_files $uri $uri/ /index.html;` for
Vue Router routes, and if you want to keep `API_BASE_URL: '/api/v1'` (relative) instead of an
absolute URL + CORS, the same `location /api/ { proxy_pass … }` block, just pointing at the
real host of your API instead of the internal `api` name from the Compose network. Also add
`add_header Cache-Control "no-store" always;` in a dedicated `location = /config.js` block, for the same
reason as in CloudFront (point 3b).

### Security Reminders for Any Standalone Deployment

- **`USE_MSW` must be `false`** in any environment reachable from outside your trusted
  network — it's the mode with no real authentication (`CLAUDE.md`). The frontend alone is not a
  sufficient barrier: also confirm that that environment's API has
  `CAPATAZ_AUTH_MODE` set to something other than `dev_mock`.
- **`OIDC_ISSUER`/`OIDC_CLIENT_ID` must point to a real IdP** (see
  [Authentik](09-authentik-oidc-setup.en.md) / [Cognito](10-cognito-oidc-setup.en.md)) in any
  environment that isn't purely local development.

## PostgreSQL Backup and Restore

Take the backup from a machine with access to the Docker daemon and store it encrypted off-host:

```bash
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T postgres pg_dump -U capataz -Fc capataz > "backups/capataz-${stamp}.dump"
sha256sum "backups/capataz-${stamp}.dump" > "backups/capataz-${stamp}.dump.sha256"
```

To restore, stop API and runner to avoid writes, verify the checksum, and restore during a maintenance window:

```bash
docker compose stop api runner
docker compose exec -T postgres dropdb -U capataz capataz
docker compose exec -T postgres createdb -U capataz capataz
cat backups/capataz-YYYYMMDDTHHMMSSZ.dump | docker compose exec -T postgres pg_restore -U capataz -d capataz --clean --if-exists
docker compose start api runner
make migrate
```

Test restores periodically in an isolated environment. Redis is not a source of truth: it can be flushed, and caches/queue regenerate according to the execution policy, but review in-flight executions before doing so.

## Portainer Token

Capataz calls the Portainer API (`X-API-Key`) for per-container status and, from the runner, for the allow-listed `portainer`-type actions. The token lives in `secrets/portainer_token` (see README) and is read in `infrastructure/secrets/file_secret_reader.py`.

1. In Portainer, create a dedicated user for Capataz (don't reuse your personal admin account) and restrict its access, via **Teams**/**Environment access**, only to the environments (endpoints) Capataz must query or operate.
2. Sign in with that user and go to **My account** (user icon, top right) → **Access tokens**.
3. **Add access token**: give it a recognizable description (e.g. `capataz-api`) so it can be unambiguously revoked later.
4. Portainer shows the token in plain text **only once**. Copy it immediately:

   ```bash
   echo 'GENERATED_TOKEN' > secrets/portainer_token
   chmod 600 secrets/portainer_token
   docker compose up -d --no-deps --force-recreate api runner
   ```

5. Verify: `docker compose logs -f api` should not show `Portainer authentication was rejected`, and a service card with containers from that environment should go from "Unknown" to a real status after clicking "Refresh status".

This token requires a separate Portainer user with permissions already restricted to the relevant environments — Portainer CE doesn't offer access tokens with a scope narrower than that of the user who generates them. Treat it like any other credential from the rotation section below.

## Credential Rotation

1. Create the new value in the corresponding provider and note a change window.
2. Replace the `secrets/` file with `umask 077`, temporarily keep a safe rollback, and apply `chmod 600`.
3. Restart only the consumers: `docker compose up -d --force-recreate api runner` (and `postgres`/`redis` when rotating their password).
4. Verify `/health/ready`, logs, and a read operation; revoke the previous value at the provider.

For PostgreSQL/Redis passwords, rotation also requires changing the database's/broker's internal credential in a coordinated way. For Portainer, scope the token to the necessary environment and operations; the runner only receives `portainer_token` because it executes platform actions. Cognito only reaches `api`. Never rotate a personal SSH key: use a dedicated automation account and a pinned `known_hosts`.

## Catalog Management

- Before importing: `POST /api/v1/catalog/import` with `{"yaml":"...","dry_run":true}` or the admin interface to get line/field errors.
- Real import: `make seed-catalog` uses the authenticated endpoint (defaults to local `dev_mock` mode). With Cognito, export `API_AUTHORIZATION='Bearer <token>'` when invoking Make; the API does a transactional upsert by the service's logical `id`, and the ID is not reused for a different service.
- Export: `make export-catalog > catalog/export.yaml`; review it and remove any metadata that shouldn't be versioned.
- Startup: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml` mounts and imports the example catalog. If the path exists but is invalid, or is missing, readiness must fail with a clear message; it is not ignored.

## Monitoring and Logs

`docker compose logs -f api`, `docker compose logs -f runner`, and searching by `X-Request-ID` are the first point of observation. In production, enable `CAPATAZ_LOG_JSON=true` and ship stdout to your collector. Cards are fed from a cache with TTL `CAPATAZ_STATUS_CACHE_TTL_SECONDS`; an explicit refresh can be triggered.

Grafana and Loki are used via declared deep-links. Measure at minimum process health, PostgreSQL/Redis availability, API latency/error rate, `automation` queue depth, terminal executions by state, duration, and integration failures. Don't include tokens, unsanitized YAML, or secrets as log labels or attributes.

## Upgrade and Rollback

1. Read release notes and validate backups/restore.
2. On a copy of the environment, run `docker compose build`, tests, and `docker compose config`.
3. Back up PostgreSQL, export the catalog, and note the current image versions (`docker compose images`).
4. In production: `make build && make up && make migrate`; watch healthchecks and one harmless `read` action.
5. If it fails, revert to the previous image tags/commit and run `docker compose up -d`. Migrations must be expand/contract; if a migration isn't reversible, restore the backup according to the release plan.

Don't use `make clean` as a normal operation: it deletes volumes after confirmation and is reserved for disposable development use.
