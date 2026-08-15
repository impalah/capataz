# ADR 007: Runtime Frontend Configuration (`config.js`), Not Build-Time

*Language: **English** · [Español](007-runtime-frontend-config.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-15

## Context

Until now the frontend read `VITE_API_BASE_URL`/`VITE_USE_MSW`/`VITE_OIDC_ISSUER`/
`VITE_OIDC_CLIENT_ID`/`VITE_OIDC_SCOPE` via `import.meta.env.VITE_*`. Vite replaces
`import.meta.env.VITE_*` with its literal value at `vite build` time, so those values ended up
baked into the static JavaScript of `dist/`. In `frontend/Dockerfile` this translated into five
`ARG`s passed as `--build-arg` from `docker-compose.yml` (in turn interpolated from `.env`);
changing any of them required rebuilding the image (`make build`/`docker compose build frontend`),
not just restarting the container.

That coupling was manageable while the only deployment target was "this repo's Docker image, in
this homelab." But Capataz needs to be distributable as a package that anyone can deploy in their
own environment — their own Docker, S3+CloudFront, an Nginx unrelated to this repo — and each
environment has its own API URL and its own OIDC provider. With the previous design that meant a
different Docker image (or a different `vite build` `dist/`) per environment, built with its own
`--build-arg`s. A static `dist/` served from S3/CloudFront doesn't even go through a build
controlled by this repo at deploy time — there is nowhere to inject a `--build-arg`.

## Decision

Frontend configuration stops being read from `import.meta.env` and is instead read at browser
runtime from `window.__APP_CONFIG__`, populated by a plain `/config.js` script loaded in
`index.html` **before** the app bundle:

```html
<script src="/config.js"></script>
<script type="module" src="/src/main.ts"></script>
```

`frontend/src/api/runtimeConfig.ts` centralizes the read (`readRuntimeConfig()`/`runtimeConfig`),
with sensible defaults if `window.__APP_CONFIG__` is missing or partial; `client.ts`, `oidc.ts`,
and the `auth.ts` store consume it instead of `import.meta.env.VITE_*`. `frontend/src/env.d.ts` no
longer declares those keys — there is no remaining code path that reads them.

`frontend/public/config.js` is a **committed** file, copied verbatim into `dist/` by Vite (like any
other asset in `public/`), with local development defaults (`USE_MSW: true`, `API_BASE_URL:
http://localhost:8000/api/v1` — the same target already assumed by Playwright's `webServer`). It
is the only file that changes per environment; the rest of `dist/`
(hashed JS/CSS, `index.html`) is identical regardless of the destination.

Two consumers of that same `dist/`, each resolving `config.js` its own way:

1. **Docker image** (`frontend/Dockerfile`, `docker-compose.yml`): no longer declares `ARG VITE_*`.
   Instead, `frontend/nginx/40-render-runtime-config.sh` — a script under
   `/docker-entrypoint.d/`, the standard convention of the `nginxinc/nginx-unprivileged` base image
   for running something before `nginx` starts — renders `frontend/nginx/config.js.template` with
   `envsubst` from `CAPATAZ_FRONTEND_*` variables (passed by `docker-compose.yml` via
   `environment:`, no longer `build.args`), and writes the result to
   `/config-runtime/config.js`. `default.conf` serves `/config.js` via a
   `location = /config.js { alias /config-runtime/config.js; }` separate from the rest of the
   static tree — which stays on the read-only filesystem (`read_only: true`) — with
   `/config-runtime` as the only additional tmpfs, 1 MB, dedicated to this. Changing the config now
   only requires recreating the container (`docker compose up -d --force-recreate frontend`), not
   rebuilding the image.
2. **Static deployment** (S3+CloudFront, a standalone Nginx): there is no container or entrypoint.
   The operator replaces `config.js` by hand in `dist/` (or in the `make build-package` zip) before
   uploading it, once per environment. See the "Standalone Deployment" section of
   `docs/07-operations.md`.

## Consequences

- **A single build serves every environment.** `npm run build`/`make build`/`make
  docker-build` no longer take any environment parameter; the artifact (`dist/` or the image) is
  identical for dev/staging/production. This is exactly what was requested: "deployable as a
  package in any environment."
- **The Docker image also becomes reconfigurable without a rebuild.** This wasn't the original
  goal, but it's a direct consequence: previously, changing `VITE_OIDC_ISSUER` in the homelab
  required a rebuild; now it's enough to recreate the container with the new value of
  `CAPATAZ_FRONTEND_OIDC_ISSUER` in `.env`.
- **New base-image requirement:** `frontend/Dockerfile` installs `gettext` (an Alpine package) for
  the `envsubst` binary — explicitly verified rather than assumed to already be present in the
  upstream `nginx` image.
- **`config.js` must never be aggressively cached.** `default.conf` sets
  `Cache-Control: no-store` on it; for the CloudFront/S3 case that policy has to be replicated by
  hand (see `docs/07-operations.md`), or a configuration change wouldn't take effect until the
  CDN/browser cache expires.
- **`envsubst` does not escape its values.** `CAPATAZ_FRONTEND_*` are operational config (URLs, a
  scope, a boolean), never end-user input, but none of them may contain `"` or `\` — that would
  break the generated JS. This is documented in the entrypoint script itself.
- **`VITE_DEV_USER` (the deterministic `dev_mock` identity used in development) becomes
  `DEV_USER`**, with the same treatment as the other fields: exposed as `CAPATAZ_FRONTEND_DEV_USER`
  in `docker-compose.yml`/`frontend/Makefile`/`.env.example`, defaulting to `ana.admin`, and present
  in `frontend/public/config.js`. Useful for deterministic tests (e.g. e2e) that need a fixed
  identity in `dev_mock` mode without touching the menu's role switcher.
- **Tests:** `Oidc.spec.ts` moves from `vi.stubEnv('VITE_OIDC_ISSUER', …)` to setting
  `window.__APP_CONFIG__` before `vi.resetModules()` — same pattern, different source. A new
  `RuntimeConfig.spec.ts` covers defaults, partial overrides, `USE_MSW` coercion (real boolean
  vs. string), and the case where `config.js` is absent. The Docker rendering (`envsubst` +
  `read_only` + tmpfs) was verified manually by building the image and starting it with
  `--read-only`; there is no automated shell test in this repo for that script.
- **Documentation:** every mention of `VITE_*`/"baked at build time" in `CLAUDE.md`,
  `docs/02-contracts.md`, `docs/08-debugging.md`, `docs/09-authentik-oidc-setup.md`,
  `docs/10-cognito-oidc-setup.md`, `frontend/README.md`, and the `errors.oidc.notConfigured` i18n
  strings (8 locales) were updated to `CAPATAZ_FRONTEND_*`/`config.js`. `docs/14-frontend-build-notes.md`
  is a dated note from a one-off validation (2026-08-08) and is left as is, as a historical record.

## Alternatives Considered

- **Keeping `--build-arg`, documenting "one build per environment."** This is exactly what we were
  explicitly asked to avoid — it does not satisfy the "one package, any environment" requirement.
- **A configuration endpoint served by the API itself** (`GET /api/v1/frontend-config` or
  similar): avoids a static file to keep in sync, but adds a blocking network call before anything
  can render (including the login screen), and a new unauthenticated public endpoint on the API
  surface — the project already deliberately avoids unnecessary surface (`CLAUDE.md`). `config.js`
  doesn't have that cost: it loads in parallel with/before the bundle, with no additional
  round-trip perceived by the user.
- **A real `.env` read by Nginx via `envsubst` inside `index.html` itself** (instead of a separate
  `config.js`): mixing the template with the SPA's entry point complicates serving it the same way
  in the static case (S3/CloudFront doesn't run `envsubst`); a separate `config.js` is a simpler
  file to substitute by hand.
- **A global variable injected by an inline script in `index.html` with placeholders like
  `__RUNTIME_API_BASE_URL__`** substituted via `sed`: functionally equivalent to `envsubst` over
  `config.js`, but reinvents a tool (`envsubst`) that the Nginx base image itself already uses and
  documents for this exact pattern.
