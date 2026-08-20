/**
 * Generic OIDC Authorization Code + PKCE client. Works against any standards-compliant
 * issuer discovered via `{issuer}/.well-known/openid-configuration` — Authentik/Keycloak/Auth0
 * for CAPATAZ_AUTH_MODE=oidc, or the Cognito Hosted UI domain for CAPATAZ_AUTH_MODE=cognito.
 * Token acquisition in the browser is identical either way; only how the API *validates* the
 * resulting access token differs, on the server side.
 */

import { i18n } from '@/i18n'
import { runtimeConfig } from '@/api/runtimeConfig'

interface DiscoveryDocument {
  issuer: string
  authorization_endpoint: string
  token_endpoint: string
  end_session_endpoint?: string
}

interface TokenResponse {
  access_token: string
  refresh_token?: string
  id_token?: string
  expires_in?: number
}

interface StoredSession {
  accessToken: string
  refreshToken?: string
  idToken?: string
  expiresAt: number
}

interface PendingLogin {
  state: string
  codeVerifier: string
  nonce: string
  redirectPath: string
}

const ISSUER = runtimeConfig.oidcIssuer
const CLIENT_ID = runtimeConfig.oidcClientId
const SCOPE = runtimeConfig.oidcScope
const CALLBACK_PATH = '/auth/callback'
const SESSION_KEY = 'capataz.oidc.session'
const PENDING_KEY = 'capataz.oidc.pending'
const EXPIRY_SKEW_MS = 30_000

export function isConfigured(): boolean {
  return Boolean(ISSUER && CLIENT_ID)
}

function issuerOrThrow(): string {
  if (!ISSUER || !CLIENT_ID) {
    throw new Error(i18n.global.t('errors.oidc.notConfigured'))
  }
  return ISSUER
}

/**
 * Parses a Response body as JSON, but on failure reports the raw (truncated) body and
 * content-type instead of the cryptic native `JSON.parse` error — the IdP or a proxy in
 * front of it returning HTML, an empty body or mis-encoded content is a common, otherwise
 * hard-to-diagnose-from-the-UI failure mode.
 */
async function parseJsonResponse<T>(response: Response, context: string): Promise<T> {
  const raw = await response.text()
  try {
    return JSON.parse(raw) as T
  } catch {
    const contentType =
      response.headers.get('content-type') ?? i18n.global.t('errors.oidc.unknownContentType')
    const snippet = raw.slice(0, 200)
    throw new Error(
      i18n.global.t('errors.oidc.nonJsonResponse', {
        context,
        status: response.status,
        contentType,
        snippet: JSON.stringify(snippet),
      }),
    )
  }
}

let discoveryCache: Promise<DiscoveryDocument> | undefined

async function discover(): Promise<DiscoveryDocument> {
  const issuer = issuerOrThrow()
  discoveryCache ??= fetch(`${issuer.replace(/\/$/, '')}/.well-known/openid-configuration`)
    .then((response) => {
      if (!response.ok) throw new Error(i18n.global.t('errors.oidc.discoveryFailed'))
      return parseJsonResponse<DiscoveryDocument>(response, i18n.global.t('errors.oidc.discoveryContext'))
    })
    .catch((error: unknown) => {
      discoveryCache = undefined
      throw error
    })
  return discoveryCache
}

function redirectUri(): string {
  return new URL(CALLBACK_PATH, window.location.origin).toString()
}

/** Only ever accept a same-app absolute path ("/foo"), never a scheme-relative or absolute URL. */
function safeRedirectPath(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) return '/'
  return path
}

function base64UrlEncode(bytes: Uint8Array): string {
  const binary = String.fromCodePoint(...bytes)
  // Standard base64url substitutions; '=' padding never appears outside the trailing position
  // in valid base64 output, so stripping every occurrence is equivalent to stripping only the
  // trailing run — and avoids a regex entirely.
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

function randomToken(length = 32): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64UrlEncode(bytes)
}

async function sha256Base64Url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input))
  return base64UrlEncode(new Uint8Array(digest))
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const [, payload] = token.split('.')
  if (!payload) return {}
  const normalized = payload
    .replaceAll('-', '+')
    .replaceAll('_', '/')
    .padEnd(payload.length + ((4 - (payload.length % 4)) % 4), '=')
  return JSON.parse(atob(normalized)) as Record<string, unknown>
}

function readSession(): StoredSession | null {
  const raw = sessionStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as StoredSession
  } catch {
    sessionStorage.removeItem(SESSION_KEY)
    return null
  }
}

function writeSession(session: StoredSession): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY)
}

export function hasSession(): boolean {
  const session = readSession()
  return Boolean(session && session.expiresAt > Date.now())
}

function persistTokens(tokens: TokenResponse): void {
  writeSession({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    idToken: tokens.id_token,
    expiresAt: Date.now() + (tokens.expires_in ?? 300) * 1000,
  })
}

/** Redirects the browser to the IdP's authorization endpoint. Never resolves on success. */
export async function beginAuthorizationRedirect(redirectPath = '/'): Promise<void> {
  const discovery = await discover()
  const codeVerifier = randomToken(48)
  const pending: PendingLogin = {
    state: randomToken(16),
    codeVerifier,
    nonce: randomToken(16),
    redirectPath: safeRedirectPath(redirectPath),
  }
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending))
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: 'code',
    scope: SCOPE,
    redirect_uri: redirectUri(),
    state: pending.state,
    nonce: pending.nonce,
    code_challenge: await sha256Base64Url(codeVerifier),
    code_challenge_method: 'S256',
  })
  window.location.assign(`${discovery.authorization_endpoint}?${params.toString()}`)
}

/** Exchanges the authorization code from `callbackUrl` for tokens. Returns the path to return to. */
export async function handleRedirectCallback(callbackUrl: string): Promise<string> {
  const url = new URL(callbackUrl)
  const error = url.searchParams.get('error')
  if (error) throw new Error(url.searchParams.get('error_description') ?? error)

  const code = url.searchParams.get('code')
  const returnedState = url.searchParams.get('state')
  const pendingRaw = sessionStorage.getItem(PENDING_KEY)
  sessionStorage.removeItem(PENDING_KEY)
  if (!code || !returnedState || !pendingRaw) {
    throw new Error(i18n.global.t('errors.oidc.incompleteLoginResponse'))
  }
  const pending = JSON.parse(pendingRaw) as PendingLogin
  if (returnedState !== pending.state) {
    throw new Error(i18n.global.t('errors.oidc.stateMismatch'))
  }

  const discovery = await discover()
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri(),
    client_id: CLIENT_ID,
    code_verifier: pending.codeVerifier,
  })
  const response = await fetch(discovery.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!response.ok) throw new Error(i18n.global.t('errors.oidc.codeRejected'))
  const tokens = await parseJsonResponse<TokenResponse>(
    response,
    i18n.global.t('errors.oidc.codeExchangeContext'),
  )

  if (tokens.id_token) {
    const claims = decodeJwtPayload(tokens.id_token)
    if (claims.nonce !== pending.nonce) {
      throw new Error(i18n.global.t('errors.oidc.nonceMismatch'))
    }
  }

  persistTokens(tokens)
  return pending.redirectPath || '/'
}

let refreshPromise: Promise<string | null> | undefined

/** Returns a valid access token, refreshing it first if it is near expiry. Null if there is no session. */
export async function getAccessToken(): Promise<string | null> {
  const session = readSession()
  if (!session) return null
  if (session.expiresAt - EXPIRY_SKEW_MS > Date.now()) return session.accessToken
  if (!session.refreshToken) {
    clearSession()
    return null
  }
  // Single-flight: several requests firing around the same time near expiry must share one
  // refresh call, not each start their own — many IdPs invalidate a refresh_token on first use,
  // so a second concurrent refresh with the same token would otherwise fail (CR-054).
  refreshPromise ??= refreshAccessToken(session.refreshToken).finally(() => {
    refreshPromise = undefined
  })
  return refreshPromise
}

async function refreshAccessToken(refreshToken: string): Promise<string | null> {
  try {
    const discovery = await discover()
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: refreshToken,
      client_id: CLIENT_ID,
    })
    const response = await fetch(discovery.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!response.ok) {
      clearSession()
      return null
    }
    const tokens = await parseJsonResponse<TokenResponse>(
      response,
      i18n.global.t('errors.oidc.refreshContext'),
    )
    persistTokens({ ...tokens, refresh_token: tokens.refresh_token ?? refreshToken })
    return readSession()?.accessToken ?? null
  } catch (error) {
    console.error('No se pudo refrescar la sesión OIDC:', error)
    clearSession()
    return null
  }
}

/**
 * Cognito's discovery document advertises a standards-shaped `end_session_endpoint`, but the
 * endpoint itself doesn't implement RP-initiated logout — passing `id_token_hint` makes it
 * bounce to `/login` with "Invalid request" instead of logging out. It only understands its own
 * proprietary `client_id` + `logout_uri` pair (see docs/10-cognito-oidc-setup.md#common-issues).
 */
function isCognitoIssuer(issuer: string): boolean {
  return /^https:\/\/cognito-idp\.[a-z0-9-]+\.amazonaws\.com\//.test(issuer)
}

/** Clears the local session and, when the IdP advertises one, redirects to its RP-initiated logout endpoint. */
export async function logout(): Promise<void> {
  const session = readSession()
  clearSession()
  if (!isConfigured()) {
    window.location.assign('/')
    return
  }
  try {
    const discovery = await discover()
    if (discovery.end_session_endpoint) {
      const params = new URLSearchParams({ client_id: CLIENT_ID })
      if (isCognitoIssuer(discovery.issuer)) {
        params.set('logout_uri', window.location.origin)
      } else {
        if (session?.idToken) params.set('id_token_hint', session.idToken)
        params.set('post_logout_redirect_uri', window.location.origin)
      }
      window.location.assign(`${discovery.end_session_endpoint}?${params.toString()}`)
      return
    }
  } catch {
    /* fall through to a local-only logout below */
  }
  window.location.assign('/')
}
