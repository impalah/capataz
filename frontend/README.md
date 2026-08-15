# Capataz frontend

*Language: **English** · [Español](README.es.md)*

Private SPA to view and operate the Capataz catalog. Built with Vue 3, Quasar 2, strict TypeScript, Pinia, and Vue Router. The client reads its configuration at runtime from `config.js` (see [ADR 007](../docs/adr/007-runtime-frontend-config.en.md)) — it defaults to `http://localhost:8000/api/v1` —, generates an `X-Request-ID` per request, and, only in `dev_mock` mode, sends `X-Dev-User` and `X-Dev-Groups`.

## Standalone development

```sh
npm install
npm run dev
```

By default, `public/config.js` enables `dev_mock` mode (`USE_MSW: true`) and provides a synthetic user with a selectable role from the top-right corner switcher (`capataz-viewer`/`capataz-operator`/`capataz-admin`) against the real API (there's no mocking in the browser — despite the flag's historical name, there was never a Mock Service Worker; see `CLAUDE.md`).

To connect to a real API with OIDC login instead of `dev_mock`, edit `public/config.js` directly (`npm run dev` serves it straight from disk, so changes apply on refresh with no rebuild): set `USE_MSW: false` and fill in `OIDC_ISSUER`/`OIDC_CLIENT_ID`. The API remains the authority: hiding a control in the UI never substitutes for its RBAC rules.

## Quality

```sh
npm run lint
npm run typecheck
npm run test:unit
npm run build
npm run e2e
```

`npm run e2e:install` installs Chromium when the environment doesn't have it. See `docs/14-frontend-build-notes.en.md` for the actual result of the last validation run.

## OpenAPI sync

The types in `src/api/types.ts` are V1's manual contract and must stay aligned with `/api/v1/openapi.json`. Once the API is available:

```sh
API_BASE_URL=http://localhost:8000 npm run generate:openapi
```

The command writes its output to `src/api/openapi.generated.ts`; the diff is reviewed and the DTOs are mapped to the application's contract. This keeps an automatic regeneration from silently changing the UI.

## Container

The `Dockerfile` is multi-stage, contains no secrets, and serves the bundle as a non-root user. Nginx listens on internal port 80 and proxies `/api/` to the contractual upstream `api:8000`, with unbuffered streaming for SSE. Compose must publish `8080:80`. The image is built once — `config.js` is rendered on every container start from `CAPATAZ_FRONTEND_*` variables (see [ADR 007](../docs/adr/007-runtime-frontend-config.en.md)); no rebuild is needed to change them.

To deploy `dist/` without Docker (S3+CloudFront, your own Nginx), see the "Standalone deployment" section of [docs/07-operations.en.md](../docs/07-operations.en.md#standalone-frontend-deployment-s3cloudfront--your-own-nginx).
