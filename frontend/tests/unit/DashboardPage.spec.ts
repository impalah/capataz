import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import DashboardPage from '@/pages/DashboardPage.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/capatazApi'
import type { Service, ServiceStatusResult } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    services: vi.fn(),
    actions: vi.fn(),
    refresh: vi.fn(),
  },
}))

const service1: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  description: 'IA interfaz',
  group_name: 'IA',
  environment: 'homelab',
}
const service2: Service = {
  id: 'immich',
  name: 'Immich',
  description: 'Fotos',
  group_name: 'Datos',
  environment: 'homelab',
}
const status: ServiceStatusResult = { service_id: 'open-webui', status: 'healthy', containers: [] }

const mountDashboard = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: DashboardPage },
      { path: '/services/:id', component: { template: '<div />' } },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(DashboardPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

const expandFilters = async (wrapper: Awaited<ReturnType<typeof mountDashboard>>['wrapper']) => {
  await wrapper.get('[aria-label="Mostrar/ocultar filtros"]').trigger('click')
  await flushPromises()
}

describe('DashboardPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.mocked(api.services).mockResolvedValue({
      items: [service1, service2],
      total: 2,
      offset: 0,
      limit: 100,
    })
    vi.mocked(api.actions).mockResolvedValue([])
    vi.mocked(api.refresh).mockResolvedValue(status)
  })

  it('loads and renders the service list, refreshing status for every service (viewer included)', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('Open WebUI')
    expect(wrapper.text()).toContain('Immich')
    // There is no cached GET .../status any more — refresh-status (viewer-accessible, always a
    // real Portainer/health/Prometheus read) is the only way to load status, for any role.
    expect(api.refresh).toHaveBeenCalledTimes(2)
    // The Servicios list has no action buttons any more (CatalogPage is the only page that
    // needs each service's action list), so fetch() must not request it here.
    expect(api.actions).not.toHaveBeenCalled()
  })

  it("renders each service's catalog-declared metrics, arriving embedded in its status", async () => {
    const statusWithMetrics = { ...status, metrics: [{ label: 'CPU', value: 12 }] }
    vi.mocked(api.refresh).mockResolvedValue(statusWithMetrics)
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('.metric-label').text()).toBe('CPU')
    expect(wrapper.get('.metric-value').text()).toBe('12.0')
  })

  it('requests the maximum page size instead of the backend default (CR-092)', async () => {
    await mountDashboard()
    expect(api.services).toHaveBeenCalledWith({ limit: '100' })
  })

  it('shows a banner when more services exist than were loaded (CR-092)', async () => {
    vi.mocked(api.services).mockResolvedValue({
      items: [service1, service2],
      total: 5,
      offset: 0,
      limit: 100,
    })
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('Mostrando 2 de 5 servicios.')
  })

  it('filters services by search text', async () => {
    const { wrapper } = await mountDashboard()
    await expandFilters(wrapper)
    await wrapper.get('.search input').setValue('Immich')
    expect(wrapper.text()).toContain('Immich')
    expect(wrapper.text()).not.toContain('Open WebUI')
  })

  it('shows an empty state when filters match nothing, and clears them on click', async () => {
    const { wrapper } = await mountDashboard()
    await expandFilters(wrapper)
    await wrapper.get('.search input').setValue('nonexistent-service')
    expect(wrapper.text()).toContain('No hay servicios con esos filtros')

    await wrapper.get('.empty-state button').trigger('click')

    expect(wrapper.text()).toContain('Open WebUI')
  })

  it('keeps the filters panel collapsed by default, expands it via the settings toggle, and remembers that choice', async () => {
    const { wrapper } = await mountDashboard()
    const filtersSection = wrapper.get('.filters').element as HTMLElement
    expect(filtersSection.style.display).toBe('none')

    await expandFilters(wrapper)
    expect(filtersSection.style.display).not.toBe('none')
    expect(localStorage.getItem('capataz.dashboardFiltersExpanded')).toBe('open')

    const { wrapper: remounted } = await mountDashboard()
    expect((remounted.get('.filters').element as HTMLElement).style.display).not.toBe('none')
  })

  it('keeps bulk-refresh available to a viewer (refresh-status is a plain read, viewer-accessible)', async () => {
    const { wrapper } = await mountDashboard()
    useAuthStore().selectDevRole('capataz-viewer')
    await flushPromises()

    const refreshAllBtn = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Actualizar todo'))

    expect(refreshAllBtn?.attributes('disabled')).toBeUndefined()
  })

  it('shows the API error banner and can retry', async () => {
    vi.mocked(api.services).mockRejectedValueOnce(new Error('down'))
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('No se pudieron cargar los servicios')

    vi.mocked(api.services).mockResolvedValueOnce({ items: [service1], total: 1, offset: 0, limit: 100 })
    await wrapper.get('.error-banner button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Open WebUI')
  })
})
