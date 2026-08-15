import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginPage from '@/pages/LoginPage.vue'
import * as oidc from '@/api/oidc'

vi.mock('@/api/oidc', () => ({
  hasSession: vi.fn(() => false),
  clearSession: vi.fn(),
  beginAuthorizationRedirect: vi.fn(),
  handleRedirectCallback: vi.fn(),
  logout: vi.fn(),
}))

const mountLogin = async (fullPath = '/login') => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', component: LoginPage }],
  })
  await router.push(fullPath)
  await router.isReady()
  const wrapper = mount(LoginPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('LoginPage', () => {
  beforeEach(() => vi.mocked(oidc.beginAuthorizationRedirect).mockReset())

  it('redirects to the OIDC provider with the requested redirect path on mount', async () => {
    vi.mocked(oidc.beginAuthorizationRedirect).mockResolvedValue(undefined)
    await mountLogin('/login?redirect=%2Fexecutions')
    expect(oidc.beginAuthorizationRedirect).toHaveBeenCalledWith('/executions')
  })

  it('defaults to "/" when there is no redirect query param', async () => {
    vi.mocked(oidc.beginAuthorizationRedirect).mockResolvedValue(undefined)
    await mountLogin('/login')
    expect(oidc.beginAuthorizationRedirect).toHaveBeenCalledWith('/')
  })

  it('shows the spinner state while redirecting', async () => {
    vi.mocked(oidc.beginAuthorizationRedirect).mockResolvedValue(undefined)
    const wrapper = await mountLogin('/login')
    expect(wrapper.text()).toContain('Redirigiendo a tu proveedor de identidad')
  })

  it('shows an error and a retry button when the redirect fails, and retries on click', async () => {
    vi.mocked(oidc.beginAuthorizationRedirect).mockRejectedValueOnce(new Error('discovery unreachable'))
    const wrapper = await mountLogin('/login')
    expect(wrapper.text()).toContain('discovery unreachable')

    vi.mocked(oidc.beginAuthorizationRedirect).mockResolvedValueOnce(undefined)
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(oidc.beginAuthorizationRedirect).toHaveBeenCalledTimes(2)
  })
})
