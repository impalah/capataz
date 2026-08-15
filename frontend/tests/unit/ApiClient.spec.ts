import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { request, ApiError } from '@/api/client'
import * as oidc from '@/api/oidc'

vi.mock('@/api/oidc', () => ({ getAccessToken: vi.fn() }))

const jsonResponse = (
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response =>
  ({
    ok: (init.status ?? 200) < 400,
    status: init.status ?? 200,
    headers: new Headers(init.headers),
    json: () => Promise.resolve(body),
  }) as unknown as Response

describe('api/client request()', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
    vi.mocked(oidc.getAccessToken).mockReset()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('attaches dev-mock identity headers, Accept and X-Request-ID when devMockEnabled', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = true
    auth.subject = 'ana.admin'
    auth.groups = ['capataz-admin']
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))

    await request('/services')

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Headers
    expect(headers.get('X-Dev-User')).toBe('ana.admin')
    expect(headers.get('X-Dev-Groups')).toBe('capataz-admin')
    expect(headers.get('Accept')).toBe('application/json')
    expect(headers.get('X-Request-ID')).toBeTruthy()
    expect(headers.get('Authorization')).toBeNull()
  })

  it('attaches a bearer token from OIDC outside dev_mock', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    vi.mocked(oidc.getAccessToken).mockResolvedValue('token-123')
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))

    await request('/services')

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Headers).get('Authorization')).toBe('Bearer token-123')
    expect((init.headers as Headers).get('X-Dev-User')).toBeNull()
  })

  it('does not attach a bearer header when no OIDC token is available', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    vi.mocked(oidc.getAccessToken).mockResolvedValue(null)
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))

    await request('/services')

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Headers).get('Authorization')).toBeNull()
  })

  it('sets Content-Type json for a body unless already set', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}))
    await request('/services', { method: 'POST', body: JSON.stringify({ a: 1 }) })
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Headers).get('Content-Type')).toBe('application/json')
  })

  it('leaves an explicitly set Content-Type untouched', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}))
    await request('/catalog/import', {
      method: 'POST',
      body: 'version: 1',
      headers: { 'Content-Type': 'application/x-yaml' },
    })
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Headers).get('Content-Type')).toBe('application/x-yaml')
  })

  it('marks the session unauthorized and throws ApiError on 401', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}, { status: 401 }))

    await expect(request('/services')).rejects.toBeInstanceOf(ApiError)
    expect(auth.unauthorized).toBe(true)
  })

  it('throws ApiError on 403 without touching session state', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}, { status: 403 }))

    await expect(request('/services')).rejects.toMatchObject({ status: 403 })
    expect(auth.unauthorized).toBe(false)
  })

  it('parses a ProblemDetail body for other errors', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'Servicio no encontrado.' }, { status: 404 }))

    await expect(request('/services/x')).rejects.toMatchObject({
      status: 404,
      message: 'Servicio no encontrado.',
    })
  })

  it('falls back to a generic message when the error body is not JSON', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers(),
      json: () => Promise.reject(new Error('not json')),
    } as unknown as Response)

    await expect(request('/services')).rejects.toMatchObject({
      status: 500,
      message: 'No se pudo completar la operación.',
    })
  })

  it('returns undefined for a 204 response', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
      json: () => Promise.resolve(undefined),
    } as unknown as Response)

    await expect(request('/services/x')).resolves.toBeUndefined()
  })

  it('resolves the parsed JSON body for a successful response', async () => {
    useAuthStore().devMockEnabled = true
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: 'open-webui' }))
    await expect(request('/services/open-webui')).resolves.toEqual({ id: 'open-webui' })
  })
})
