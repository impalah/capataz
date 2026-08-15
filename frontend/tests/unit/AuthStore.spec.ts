import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/capatazApi'
import * as oidc from '@/api/oidc'
import type { Identity } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({ api: { me: vi.fn() } }))
vi.mock('@/api/oidc', () => ({
  hasSession: vi.fn(),
  clearSession: vi.fn(),
  beginAuthorizationRedirect: vi.fn(),
  handleRedirectCallback: vi.fn(),
  logout: vi.fn(),
}))

const identity: Identity = { subject: 'ana.oidc', email: 'ana@lab.local', groups: ['capataz-operator'] }

describe('useAuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('displayName prefers name, then email, then the raw subject', () => {
    const store = useAuthStore()
    store.subject = 'c2353494-5041-70b5-20f3-d4da5ba6be91'
    store.email = undefined as unknown as string
    store.name = undefined
    expect(store.displayName).toBe('c2353494-5041-70b5-20f3-d4da5ba6be91')
    store.email = 'ana@lab.local'
    expect(store.displayName).toBe('ana@lab.local')
    store.name = 'Ana Admin'
    expect(store.displayName).toBe('Ana Admin')
  })

  it('enforces role hierarchy in client affordances', () => {
    const store = useAuthStore()
    store.selectDevRole('capataz-viewer')
    // Viewers can execute 'read' actions but nothing riskier (docs/06-security.en.md RBAC hierarchy).
    expect(store.canExecute('read')).toBe(true)
    expect(store.canExecute('operate')).toBe(false)
    store.selectDevRole('capataz-operator')
    expect(store.canExecute('operate')).toBe(true)
    expect(store.canExecute('critical')).toBe(false)
    store.selectDevRole('capataz-admin')
    expect(store.canExecute('critical')).toBe(true)
  })

  it('records unauthorized state', () => {
    const store = useAuthStore()
    store.markUnauthorized()
    expect(store.unauthorized).toBe(true)
  })

  it('load() bootstraps identity from an existing OIDC session', async () => {
    const store = useAuthStore()
    store.devMockEnabled = false
    vi.mocked(oidc.hasSession).mockReturnValue(true)
    vi.mocked(api.me).mockResolvedValue(identity)

    await store.load()

    expect(store.isLoggedIn).toBe(true)
    expect(store.initialized).toBe(true)
    expect(store.subject).toBe('ana.oidc')
    expect(store.groups).toEqual(['capataz-operator'])
  })

  it('load() leaves the user logged out when there is no session', async () => {
    const store = useAuthStore()
    store.devMockEnabled = false
    vi.mocked(oidc.hasSession).mockReturnValue(false)

    await store.load()

    expect(store.isLoggedIn).toBe(false)
    expect(store.initialized).toBe(true)
    expect(api.me).not.toHaveBeenCalled()
  })

  it('load() clears a stale session when /auth/me rejects it', async () => {
    const store = useAuthStore()
    store.devMockEnabled = false
    vi.mocked(oidc.hasSession).mockReturnValue(true)
    vi.mocked(api.me).mockRejectedValue(new Error('401'))

    await store.load()

    expect(store.isLoggedIn).toBe(false)
    expect(oidc.clearSession).toHaveBeenCalledOnce()
  })

  it('load() only bootstraps once for concurrent callers', async () => {
    const store = useAuthStore()
    store.devMockEnabled = false
    vi.mocked(oidc.hasSession).mockReturnValue(true)
    vi.mocked(api.me).mockResolvedValue(identity)

    await Promise.all([store.load(), store.load(), store.load()])

    expect(api.me).toHaveBeenCalledOnce()
  })

  it('startLogin() delegates to the OIDC client with the redirect path', async () => {
    const store = useAuthStore()
    await store.startLogin('/executions')
    expect(oidc.beginAuthorizationRedirect).toHaveBeenCalledWith('/executions')
  })

  it('completeLogin() exchanges the callback, loads identity and returns the redirect path', async () => {
    const store = useAuthStore()
    vi.mocked(oidc.handleRedirectCallback).mockResolvedValue('/executions')
    vi.mocked(api.me).mockResolvedValue(identity)

    const redirectPath = await store.completeLogin('https://capataz.home.arpa/auth/callback?code=x&state=y')

    expect(redirectPath).toBe('/executions')
    expect(store.isLoggedIn).toBe(true)
    expect(store.initialized).toBe(true)
    expect(store.subject).toBe('ana.oidc')
  })

  it('logout() clears local state and delegates to the OIDC client', async () => {
    const store = useAuthStore()
    store.isLoggedIn = true
    store.initialized = true

    await store.logout()

    expect(store.isLoggedIn).toBe(false)
    expect(store.initialized).toBe(false)
    expect(oidc.logout).toHaveBeenCalledOnce()
  })

  it('markUnauthorized() drops the OIDC session outside dev_mock', () => {
    const store = useAuthStore()
    store.devMockEnabled = false
    store.isLoggedIn = true
    store.initialized = true

    store.markUnauthorized()

    expect(store.unauthorized).toBe(true)
    expect(store.isLoggedIn).toBe(false)
    expect(store.initialized).toBe(false)
    expect(oidc.clearSession).toHaveBeenCalledOnce()
  })
})
