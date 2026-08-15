/**
 * Runtime configuration, read from `window.__APP_CONFIG__` — populated by `/config.js`, a plain
 * script loaded before the app bundle (see index.html). This is what lets a single `dist/`
 * artifact be deployed to any environment (Docker, S3+CloudFront, a bare Nginx) by swapping only
 * `config.js`, never by rebuilding: see docs/adr/007-runtime-frontend-config.en.md.
 *
 * `public/config.js` ships local-development defaults and is copied verbatim into `dist/` by
 * Vite. The Docker image overwrites it at container start (frontend/nginx/40-render-runtime-config.sh);
 * a static deploy overwrites it by hand per environment.
 */

export interface RuntimeConfig {
  apiBaseUrl: string
  useMsw: boolean
  devUser: string
  oidcIssuer: string
  oidcClientId: string
  oidcScope: string
}

interface WindowAppConfig {
  API_BASE_URL?: string
  USE_MSW?: boolean | string
  DEV_USER?: string
  OIDC_ISSUER?: string
  OIDC_CLIENT_ID?: string
  OIDC_SCOPE?: string
}

declare global {
  interface Window {
    __APP_CONFIG__?: WindowAppConfig
  }
}

const DEFAULTS: RuntimeConfig = {
  apiBaseUrl: '/api/v1',
  useMsw: false,
  devUser: 'ana.admin',
  oidcIssuer: '',
  oidcClientId: '',
  oidcScope: 'openid profile email groups',
}

/** Accepts both a real boolean and the string a hand-edited/envsubst-rendered config.js may carry. */
function coerceBool(value: boolean | string | undefined): boolean | undefined {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') return value === 'true'
  return undefined
}

export function readRuntimeConfig(): RuntimeConfig {
  const raw: WindowAppConfig | undefined = typeof window !== 'undefined' ? window.__APP_CONFIG__ : undefined
  return {
    apiBaseUrl: raw?.API_BASE_URL || DEFAULTS.apiBaseUrl,
    useMsw: coerceBool(raw?.USE_MSW) ?? DEFAULTS.useMsw,
    devUser: raw?.DEV_USER || DEFAULTS.devUser,
    oidcIssuer: raw?.OIDC_ISSUER || DEFAULTS.oidcIssuer,
    oidcClientId: raw?.OIDC_CLIENT_ID || DEFAULTS.oidcClientId,
    oidcScope: raw?.OIDC_SCOPE || DEFAULTS.oidcScope,
  }
}

export const runtimeConfig: RuntimeConfig = readRuntimeConfig()
