// Runtime configuration for the Capataz frontend, loaded by index.html before the app bundle.
// This file ships with LOCAL-DEVELOPMENT defaults (dev_mock enabled, API reachable directly on
// :8000 — the same target `npm run dev` and Playwright's local e2e webServer already assumed).
//
// It is NOT meant to be the config that reaches a real deployment as-is:
//   - The Docker image overwrites this exact file at container start, rendered from
//     CAPATAZ_FRONTEND_* environment variables — see frontend/nginx/40-render-runtime-config.sh.
//   - A static deploy (S3/CloudFront, a bare Nginx) must replace this file per environment,
//     after `npm run build`, before/while uploading dist/.
//
// See docs/adr/007-runtime-frontend-config.en.md and the "Standalone Frontend Deployment" section of
// docs/07-operations.en.md.
window.__APP_CONFIG__ = {
  API_BASE_URL: 'http://localhost:8000/api/v1',
  USE_MSW: true,
  // Identidad sintética inicial en modo dev_mock (USE_MSW: true), antes de tocar el selector de
  // rol del menú de cuenta. Solo tiene efecto con USE_MSW: true.
  DEV_USER: 'ana.admin',
  OIDC_ISSUER: '',
  OIDC_CLIENT_ID: '',
  OIDC_SCOPE: 'openid profile email groups',
}
