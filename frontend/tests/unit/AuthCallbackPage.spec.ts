import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AuthCallbackPage from '@/pages/AuthCallbackPage.vue'
import * as oidc from '@/api/oidc'
import { api } from '@/api/capatazApi'
import type { Identity } from '@/api/types'

vi.mock('@/api/oidc', () => ({
  hasSession: vi.fn(),
  clearSession: vi.fn(),
  beginAuthorizationRedirect: vi.fn(),
  handleRedirectCallback: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('@/api/capatazApi', () => ({ api: { me: vi.fn() } }))

const identity: Identity = { subject: 'ana.oidc', email: 'ana@lab.local', groups: ['capataz-operator'] }

const mountCallback = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/auth/callback', component: AuthCallbackPage },
      { path: '/executions', component: { template: '<div />' } },
      { path: '/', component: { template: '<div />' } },
    ],
  })
  await router.push('/auth/callback')
  await router.isReady()
  const wrapper = mount(AuthCallbackPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('AuthCallbackPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('exchanges the callback and replaces the route with the path returned by the OIDC client', async () => {
    vi.mocked(oidc.handleRedirectCallback).mockResolvedValue('/executions')
    vi.mocked(api.me).mockResolvedValue(identity)

    const { router } = await mountCallback()

    expect(router.currentRoute.value.fullPath).toBe('/executions')
  })

  it('shows the spinner state while completing login', async () => {
    vi.mocked(oidc.handleRedirectCallback).mockImplementation(() => new Promise(() => undefined))
    const { wrapper } = await mountCallback()
    expect(wrapper.text()).toContain('Completando inicio de sesión')
  })

  it('shows an error with a retry action when the exchange fails', async () => {
    vi.mocked(oidc.handleRedirectCallback).mockRejectedValue(new Error('invalid state'))
    const { wrapper } = await mountCallback()

    expect(wrapper.text()).toContain('invalid state')

    vi.mocked(oidc.beginAuthorizationRedirect).mockResolvedValue(undefined)
    await wrapper.get('button').trigger('click')

    expect(oidc.beginAuthorizationRedirect).toHaveBeenCalledWith('/')
  })
})
