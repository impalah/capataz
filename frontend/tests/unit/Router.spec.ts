import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'
import type { Role } from '@/api/types'

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

  it.each([
    {
      description: 'lets an authenticated non-admin reach ordinary routes',
      groups: ['capataz-viewer'] as Role[],
      path: '/executions',
      expectedName: 'executions',
    },
    {
      description: 'bounces an authenticated non-admin away from admin-only routes to the dashboard',
      groups: ['capataz-operator'] as Role[],
      path: '/catalog',
      expectedName: 'dashboard',
    },
    {
      description: 'lets an admin reach admin-only routes',
      groups: ['capataz-admin'] as Role[],
      path: '/audit',
      expectedName: 'audit',
    },
  ])('$description', async ({ groups, path, expectedName }) => {
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.loadPromise = Promise.resolve()
    auth.isLoggedIn = true
    auth.initialized = true
    auth.groups = groups

    await router.push(path)

    expect(router.currentRoute.value.name).toBe(expectedName)
  })

  it('dev_mode bypasses the login redirect even without an explicit "logged in" flag', async () => {
    const auth = useAuthStore()
    auth.devMockEnabled = true

    await router.push('/')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })
})
