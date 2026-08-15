import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  // Must be http://localhost:9000, not 127.0.0.1:9000: CORS treats them as different origins, and
  // CAPATAZ_CORS_ORIGINS (see .env.example) only allows http://localhost:9000.
  use: { baseURL: 'http://localhost:9000', trace: 'on-first-retry' },
  webServer: {
    // dev_mock synthetic-admin mode against a real, already-running api (see docker-compose.yml /
    // CI's e2e job) — no more MSW/fixture mocking. CORS on the api side already allows this origin
    // (CAPATAZ_CORS_ORIGINS includes http://localhost:9000) for exactly this local-dev workflow.
    // No env vars needed: public/config.js already ships dev_mock=true and this exact API URL as
    // its committed default — see docs/adr/007-runtime-frontend-config.en.md.
    command: 'npm run dev',
    url: 'http://localhost:9000',
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
