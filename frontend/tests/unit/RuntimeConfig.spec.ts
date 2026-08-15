import { readRuntimeConfig } from '@/api/runtimeConfig'

describe('runtimeConfig', () => {
  afterEach(() => {
    delete window.__APP_CONFIG__
  })

  it('falls back to built-in defaults when window.__APP_CONFIG__ is absent (config.js failed to load)', () => {
    expect(readRuntimeConfig()).toEqual({
      apiBaseUrl: '/api/v1',
      useMsw: false,
      devUser: 'ana.admin',
      oidcIssuer: '',
      oidcClientId: '',
      oidcScope: 'openid profile email groups',
    })
  })

  it('reads every field from window.__APP_CONFIG__ when present', () => {
    window.__APP_CONFIG__ = {
      API_BASE_URL: 'https://api.example.com/api/v1',
      USE_MSW: false,
      DEV_USER: 'someone.else',
      OIDC_ISSUER: 'https://idp.example.com/',
      OIDC_CLIENT_ID: 'capataz-prod',
      OIDC_SCOPE: 'openid profile',
    }

    expect(readRuntimeConfig()).toEqual({
      apiBaseUrl: 'https://api.example.com/api/v1',
      useMsw: false,
      devUser: 'someone.else',
      oidcIssuer: 'https://idp.example.com/',
      oidcClientId: 'capataz-prod',
      oidcScope: 'openid profile',
    })
  })

  it('accepts USE_MSW as a real boolean (Docker entrypoint renders it unquoted)', () => {
    window.__APP_CONFIG__ = { USE_MSW: true }
    expect(readRuntimeConfig().useMsw).toBe(true)
  })

  it('accepts USE_MSW as a string (hand-edited config.js)', () => {
    window.__APP_CONFIG__ = { USE_MSW: 'true' }
    expect(readRuntimeConfig().useMsw).toBe(true)

    window.__APP_CONFIG__ = { USE_MSW: 'false' }
    expect(readRuntimeConfig().useMsw).toBe(false)
  })

  it('falls back to defaults field-by-field for a partial config.js, not all-or-nothing', () => {
    window.__APP_CONFIG__ = { OIDC_ISSUER: 'https://idp.example.com/' }

    const config = readRuntimeConfig()

    expect(config.oidcIssuer).toBe('https://idp.example.com/')
    expect(config.apiBaseUrl).toBe('/api/v1')
    expect(config.useMsw).toBe(false)
    expect(config.oidcScope).toBe('openid profile email groups')
  })

  it('treats an empty string the same as an absent field (falls back to the default)', () => {
    window.__APP_CONFIG__ = { API_BASE_URL: '', OIDC_ISSUER: '' }

    const config = readRuntimeConfig()

    expect(config.apiBaseUrl).toBe('/api/v1')
    expect(config.oidcIssuer).toBe('')
  })
})
