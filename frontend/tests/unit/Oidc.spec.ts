import type * as OidcModule from '@/api/oidc'

const DISCOVERY = {
  issuer: 'https://idp.home.arpa/application/o/capataz/',
  authorization_endpoint: 'https://idp.home.arpa/application/o/authorize/',
  token_endpoint: 'https://idp.home.arpa/application/o/token/',
  end_session_endpoint: 'https://idp.home.arpa/application/o/end-session/',
}

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 400,
    text: () => Promise.resolve(JSON.stringify(body)),
    headers: new Headers({ 'content-type': 'application/json' }),
  } as Response
}

function rawResponse(body: string, contentType = 'text/html'): Response {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(body),
    headers: new Headers({ 'content-type': contentType }),
  } as Response
}

describe('oidc client (Authorization Code + PKCE)', () => {
  let oidc: typeof OidcModule

  beforeEach(async () => {
    sessionStorage.clear()
    window.__APP_CONFIG__ = {
      OIDC_ISSUER: 'https://idp.home.arpa/application/o/capataz/',
      OIDC_CLIENT_ID: 'capataz-test',
    }
    vi.resetModules()
    oidc = await import('@/api/oidc')
    // oidc.ts calls i18n.global.t() on the @/i18n singleton, which vi.resetModules() just gave a
    // fresh instance of (locale re-detected from happy-dom's navigator, not the es-ES tests/setup.ts
    // configured) — repin it so error messages match the assertions below.
    const { i18n } = await import('@/i18n')
    i18n.global.locale.value = 'es-ES'
    vi.stubGlobal('fetch', vi.fn())
    vi.spyOn(window.location, 'assign').mockImplementation(() => {})
  })

  afterEach(() => {
    delete window.__APP_CONFIG__
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('has no session before any login', () => {
    expect(oidc.hasSession()).toBe(false)
  })

  it('redirects to the discovered authorization_endpoint with PKCE S256 and stores pending state', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))

    await oidc.beginAuthorizationRedirect('/executions')

    expect(window.location.assign).toHaveBeenCalledOnce()
    const url = new URL(vi.mocked(window.location.assign).mock.calls[0]?.[0] as string)
    expect(url.origin + url.pathname).toBe(DISCOVERY.authorization_endpoint)
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
    expect(url.searchParams.get('code_challenge')).toBeTruthy()
    expect(url.searchParams.get('state')).toBeTruthy()

    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    expect(pending.redirectPath).toBe('/executions')
    expect(pending.state).toBe(url.searchParams.get('state'))
  })

  it('rejects a callback whose state does not match the pending login (CSRF)', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')

    await expect(
      oidc.handleRedirectCallback(
        'https://capataz.home.arpa/auth/callback?code=abc&state=not-the-real-state',
      ),
    ).rejects.toThrow(/state/i)
  })

  it('rejects a callback that carries an IdP error', async () => {
    await expect(
      oidc.handleRedirectCallback(
        'https://capataz.home.arpa/auth/callback?error=access_denied&error_description=nope',
      ),
    ).rejects.toThrow('nope')
  })

  it('surfaces the raw body when the token endpoint returns a non-JSON response', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)

    vi.mocked(fetch).mockResolvedValueOnce(rawResponse('<html><body>502 Bad Gateway</body></html>'))

    await expect(
      oidc.handleRedirectCallback(`https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`),
    ).rejects.toThrow(/no-JSON.*text\/html.*502 Bad Gateway/s)
  })

  it('exchanges the code for tokens with the stored PKCE verifier and persists the session', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/executions')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)

    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ access_token: 'access-1', refresh_token: 'refresh-1', expires_in: 300 }),
    )

    const redirectPath = await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc123&state=${pending.state}`,
    )

    expect(redirectPath).toBe('/executions')
    expect(oidc.hasSession()).toBe(true)
    expect(await oidc.getAccessToken()).toBe('access-1')

    const tokenCall = vi.mocked(fetch).mock.calls[1]
    const body = tokenCall?.[1]?.body as URLSearchParams
    expect(body.get('grant_type')).toBe('authorization_code')
    expect(body.get('code_verifier')).toBe(pending.codeVerifier)
    expect(body.get('code')).toBe('abc123')
    expect(sessionStorage.getItem('capataz.oidc.pending')).toBeNull()
  })

  it('refreshes an expired access token transparently', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ access_token: 'access-1', refresh_token: 'refresh-1', expires_in: -10 }),
    )
    await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`,
    )

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ access_token: 'access-2', expires_in: 300 }))
    const token = await oidc.getAccessToken()

    expect(token).toBe('access-2')
    const refreshCall = vi.mocked(fetch).mock.calls[2]
    const body = refreshCall?.[1]?.body as URLSearchParams
    expect(body.get('grant_type')).toBe('refresh_token')
    expect(body.get('refresh_token')).toBe('refresh-1')
  })

  it('deduplicates concurrent refresh calls into a single in-flight request (CR-054)', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ access_token: 'access-1', refresh_token: 'refresh-1', expires_in: -10 }),
    )
    await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`,
    )

    const callsBeforeRefresh = vi.mocked(fetch).mock.calls.length
    // Only one refresh response is queued — if getAccessToken() ever issued two concurrent
    // refresh requests, the second would consume no mock and fail.
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ access_token: 'access-2', expires_in: 300 }))

    const [first, second] = await Promise.all([oidc.getAccessToken(), oidc.getAccessToken()])

    expect(first).toBe('access-2')
    expect(second).toBe('access-2')
    expect(vi.mocked(fetch).mock.calls).toHaveLength(callsBeforeRefresh + 1)
  })

  it('clears the session when refresh fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ access_token: 'access-1', expires_in: -10 }))
    await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`,
    )

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({}, false))
    const token = await oidc.getAccessToken()

    expect(token).toBeNull()
    expect(oidc.hasSession()).toBe(false)
  })

  it('logout() clears the local session and redirects to the RP-initiated end_session endpoint', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ access_token: 'access-1', expires_in: 300 }))
    await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`,
    )

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(DISCOVERY))
    await oidc.logout()

    expect(oidc.hasSession()).toBe(false)
    const url = new URL(vi.mocked(window.location.assign).mock.calls.at(-1)?.[0] as string)
    expect(url.origin + url.pathname).toBe(DISCOVERY.end_session_endpoint)
    expect(url.searchParams.get('post_logout_redirect_uri')).toBe(window.location.origin)
    expect(url.searchParams.has('logout_uri')).toBe(false)
  })

  it("logout() against a Cognito issuer uses logout_uri instead of id_token_hint (Cognito's /logout doesn't support RP-initiated logout despite advertising end_session_endpoint)", async () => {
    window.__APP_CONFIG__ = {
      OIDC_ISSUER: 'https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_T1JkF6VNE',
      OIDC_CLIENT_ID: 'cognito-test',
    }
    vi.resetModules()
    oidc = await import('@/api/oidc')
    const COGNITO_DISCOVERY = {
      issuer: 'https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_T1JkF6VNE',
      authorization_endpoint: 'https://capataz.auth.eu-west-1.amazoncognito.com/oauth2/authorize',
      token_endpoint: 'https://capataz.auth.eu-west-1.amazoncognito.com/oauth2/token',
      end_session_endpoint: 'https://capataz.auth.eu-west-1.amazoncognito.com/logout',
    }

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(COGNITO_DISCOVERY))
    await oidc.beginAuthorizationRedirect('/')
    const pending = JSON.parse(sessionStorage.getItem('capataz.oidc.pending') as string)
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ access_token: 'access-1', expires_in: 300 }))
    await oidc.handleRedirectCallback(
      `https://capataz.home.arpa/auth/callback?code=abc&state=${pending.state}`,
    )

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(COGNITO_DISCOVERY))
    await oidc.logout()

    const url = new URL(vi.mocked(window.location.assign).mock.calls.at(-1)?.[0] as string)
    expect(url.origin + url.pathname).toBe(COGNITO_DISCOVERY.end_session_endpoint)
    expect(url.searchParams.get('logout_uri')).toBe(window.location.origin)
    expect(url.searchParams.has('id_token_hint')).toBe(false)
    expect(url.searchParams.has('post_logout_redirect_uri')).toBe(false)
  })
})
