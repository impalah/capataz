import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

/**
 * router.beforeEach (src/router/index.ts) is the guard described in CLAUDE.md:
 * meta.public bypasses auth entirely; outside dev_mock an unauthenticated user is sent to
 * /login with a redirect query; meta.admin additionally requires isAdmin.
 *
 * Setting `loadPromise` directly short-circuits auth.load() (it only ever awaits that promise
 * once resolved) so these tests exercise the guard without a real OIDC/API round trip.
 */
describe('router guards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('lets public routes through without ever touching auth state', async () => {
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('redirects an unauthenticated, non-dev_mock user to /login with a redirect query', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.loadPromise = Promise.resolve()
    auth.isLoggedIn = false
    auth.initialized = true

    await router.push('/executions')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/executions')
  })

  it('lets an authenticated non-admin reach ordinary routes', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.loadPromise = Promise.resolve()
    auth.isLoggedIn = true
    auth.initialized = true
    auth.groups = ['capataz-viewer']

    await router.push('/executions')

    expect(router.currentRoute.value.name).toBe('executions')
  })

  it('bounces an authenticated non-admin away from admin-only routes to the dashboard', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.loadPromise = Promise.resolve()
    auth.isLoggedIn = true
    auth.initialized = true
    auth.groups = ['capataz-operator']

    await router.push('/catalog')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('lets an admin reach admin-only routes', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.loadPromise = Promise.resolve()
    auth.isLoggedIn = true
    auth.initialized = true
    auth.groups = ['capataz-admin']

    await router.push('/audit')

    expect(router.currentRoute.value.name).toBe('audit')
  })

  it('dev_mode bypasses the login redirect even without an explicit "logged in" flag', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = true

    await router.push('/')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })
})
