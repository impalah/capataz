# Build notes — Capataz frontend

*Language: **English** · [Español](14-frontend-build-notes.es.md)*

> This note is updated once validation is finished. Check the command outputs in the build history if you need the detail of a specific issue.

## Implemented

- Vue 3 / Quasar 2 SPA with strict TypeScript, Composition API, Pinia, and Vue Router.
- Typed `fetch` client under `src/api/`: base URL `/api/v1`, `X-Request-ID`, explicit handling of 401/403, and the exact development headers `X-Dev-User` / `X-Dev-Groups`.
- Domain types aligned with `docs/02-contracts.md`: statuses, risk levels, action types, roles, executions, events, and audit. `README.md` documents the future generation from OpenAPI.
- `useAuthStore`, `useServicesStore`, and `useExecutionsStore` stores; a dev_mock role selector for deterministic tests.
- Filterable dashboard with loading/error/empty states, service detail, actions with mandatory confirmation/reason for `critical`, a QTable history, execution view with timeline/SSE, catalog with service CRUD and action creation, YAML dry-run/import/export, and admin-protected audit.
- `VITE_USE_MSW=true` enables a no-login mode: a synthetic user with a role selector (viewer/operator/admin) that calls the real API via `CAPATAZ_AUTH_MODE=dev_mock` — there are no mocks in the browser, the SPA always talks to the real backend. It is disabled with `VITE_USE_MSW=false` to test real OIDC/Cognito login.
- Multi-stage Docker image with no secrets. Non-root Nginx listens on 80; `/api/` proxies to `api:8000`, including SSE support.

## Validation performed

The following commands were run from this directory on 2026-08-08:

| Command | Result |
|---|---|
| `npm install` | Successful; npm reported 3 transitive vulnerabilities (2 high, 1 critical), without applying a potentially breaking update. |
| `npm run lint` | Successful. |
| `npm run typecheck` | Successful (`vue-tsc --noEmit`). |
| `npm run test:unit` | Successful: 4 files, 10 tests; coverage of the included units: 100% statements/lines, 87.87% branches, 80% functions. |
| `npm run build` | Successful; production Vite bundle generated in `dist/`. |
| `npx playwright install --with-deps chromium` | Successful; Chromium and its dependencies installed in the sandbox. |
| `npm run e2e` | Successful: 2 Chromium tests. Covers the admin flow (services, detail, critical confirmation, execution, YAML import) and viewer visibility. |

A first literal invocation of `npm run test:unit -- --coverage` duplicated `--coverage` because the script already includes it; the correct equivalent run was `npm run test:unit`, and that is the one recorded in the table. During bootstrap, `npm install` was attempted from the global working directory; this was fixed by running it with the subproject prefix, without modifying anything outside `frontend/`.

## V1 decisions and limits

- `ExecutionPage.vue` polls `GET /executions/{id}` + `GET /executions/{id}/events` every 3s while the execution is non-terminal, instead of using the SSE endpoint `GET /executions/{id}/events/stream` — `EventSource` does not allow attaching headers (neither `Authorization: Bearer` nor `X-Dev-User`/`X-Dev-Groups`), so that endpoint could only be authenticated under `dev_mock`. The endpoint still exists (authenticated, usable by API consumers that can attach a header), but the frontend no longer calls it.
- The UI uses the claims for ergonomics, but the API re-authorizes mutations. 403 responses are presented without internal details.
- The actions form keeps a minimal declarative configuration; it does not expose fields for commands, arbitrary URLs, or arbitrary playbooks.
- The Docker image was not built in this sandbox because Docker daemon availability was not assumed. The SPA's production build did pass; the Dockerfile uses `npm ci`, so it consumes the generated `package-lock.json`.
