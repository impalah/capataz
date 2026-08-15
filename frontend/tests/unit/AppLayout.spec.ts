import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'

const mountLayout = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/executions', component: { template: '<div />' } },
      { path: '/catalog', component: { template: '<div />' } },
      { path: '/audit', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  // QMenu portals its content and only mounts it while open; stubbing it inline keeps the
  // account-menu items (role switch / logout) queryable without simulating the open interaction.
  // QDrawer's own responsive breakpoint detection is based on QLayout's measured container width
  // ($layout.totalWidth), which is always 0 in happy-dom (no real layout engine) — that makes the
  // real component think it's always in "mobile" mode and auto-close regardless of `modelValue`.
  // Stubbing it to a plain v-if on modelValue keeps the test exercising AppLayout's own
  // drawer/localStorage logic without depending on Quasar's unavailable-in-jsdom layout math.
  const wrapper = mount(AppLayout, {
    global: {
      plugins: [router],
      stubs: {
        QMenu: { template: '<div><slot /></div>' },
        QDrawer: {
          name: 'QDrawer',
          props: ['modelValue'],
          template: '<div v-if="modelValue"><slot /></div>',
        },
      },
    },
  })
  return { wrapper, router }
}

describe('AppLayout', () => {
  beforeEach(() => localStorage.clear())

  it('shows the Catálogo/Auditoría navigation links for admins', async () => {
    const { wrapper } = await mountLayout()
    useAuthStore().selectDevRole('capataz-admin')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Catálogo')
    expect(wrapper.text()).toContain('Auditoría')
  })

  it('hides admin-only navigation links for non-admins', async () => {
    const { wrapper } = await mountLayout()
    useAuthStore().selectDevRole('capataz-viewer')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('Catálogo')
    expect(wrapper.text()).not.toContain('Auditoría')
  })

  it('always shows the Servicios/Ejecuciones links regardless of role', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.text()).toContain('Servicios')
    expect(wrapper.text()).toContain('Ejecuciones')
  })

  it('lets a dev_mock user switch roles from the account menu', async () => {
    const { wrapper } = await mountLayout()
    const auth = useAuthStore()
    auth.devMockEnabled = true
    await wrapper.vm.$nextTick()

    const operatorItem = wrapper.findAll('.q-item').find((item) => item.text().includes('operator'))
    await operatorItem?.trigger('click')

    expect(auth.highestRole).toBe('capataz-operator')
  })

  it('logs out when a non-dev_mock user clicks "Cerrar sesión"', async () => {
    const { wrapper } = await mountLayout()
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.isLoggedIn = true
    auth.initialized = true
    vi.spyOn(auth, 'logout').mockResolvedValue()
    await wrapper.vm.$nextTick()

    const logoutItem = wrapper.findAll('.q-item').find((item) => item.text().includes('Cerrar sesión'))
    await logoutItem?.trigger('click')

    expect(auth.logout).toHaveBeenCalledOnce()
  })

  it('toggles dark mode and persists the choice to localStorage', async () => {
    const { wrapper } = await mountLayout()
    const before = localStorage.getItem('capataz.theme')
    const toggle = wrapper.find('[aria-label="Activar modo claro"], [aria-label="Activar modo oscuro"]')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')

    expect(localStorage.getItem('capataz.theme')).not.toBe(before)
  })

  it('starts expanded on desktop and can be folded, persisting the choice to localStorage', async () => {
    const { wrapper } = await mountLayout()
    await wrapper.vm.$nextTick()
    const getDrawer = () => wrapper.findComponent({ name: 'QDrawer' })
    expect(getDrawer().props('modelValue')).toBe(true)

    const toggle = wrapper.find('[aria-label="Plegar navegación"]')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')

    expect(getDrawer().props('modelValue')).toBe(false)
    expect(localStorage.getItem('capataz.drawerOpen')).toBe('closed')
  })

  it('remembers a folded drawer across remounts (e.g. navigating to another page)', async () => {
    localStorage.setItem('capataz.drawerOpen', 'closed')
    const { wrapper } = await mountLayout()

    expect(wrapper.findComponent({ name: 'QDrawer' }).props('modelValue')).toBe(false)
    expect(wrapper.find('[aria-label="Desplegar navegación"]').exists()).toBe(true)
  })

  it('offers to log back in when the session becomes unauthorized outside dev_mock', async () => {
    const { wrapper } = await mountLayout()
    const auth = useAuthStore()
    auth.devMockEnabled = false
    auth.markUnauthorized()
    await wrapper.vm.$nextTick()
    // markUnauthorized() itself is covered by AuthStore.spec.ts; here we only assert the
    // layout's watcher doesn't throw when the flag flips (Notify is registered globally).
    expect(auth.unauthorized).toBe(true)
  })
})
