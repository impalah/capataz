import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { defineComponent, h } from 'vue'
import ServiceDetailPage from '@/pages/ServiceDetailPage.vue'
import { api } from '@/api/capatazApi'
import { useAuthStore } from '@/stores/auth'
import type { ActionDefinition, Execution, Service, ServiceStatusResult } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    service: vi.fn(),
    actions: vi.fn(),
    links: vi.fn(),
    status: vi.fn(),
    refresh: vi.fn(),
    executions: vi.fn(),
    execute: vi.fn(),
  },
}))

const service: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  description: 'Interfaz de modelos.',
  group_name: 'IA',
  environment: 'homelab',
  icon: 'smart_toy',
}
const otherService: Service = {
  id: 'immich',
  name: 'Immich',
  description: 'Fotos.',
  group_name: 'Media',
  environment: 'homelab',
  icon: 'photo',
}
const status: ServiceStatusResult = {
  service_id: 'open-webui',
  status: 'healthy',
  containers: [{ name: 'open-webui', running: true, healthy: true }],
}
const otherStatus: ServiceStatusResult = {
  service_id: 'immich',
  status: 'healthy',
  containers: [{ name: 'immich', running: true, healthy: true }],
}
const restartAction: ActionDefinition = {
  id: 'a1',
  service_id: 'open-webui',
  key: 'restart',
  label: 'Reiniciar',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  config: {},
}
const execution: Execution = {
  id: 'e-1',
  service_id: 'open-webui',
  service_id_snapshot: 'open-webui',
  action_definition_id: 'a1',
  action_key: 'restart',
  requested_by_subject: 'ana',
  source: 'ui',
  params: {},
  status: 'succeeded',
  requested_at: '2026-01-01T10:00:00.000Z',
  correlation_id: 'corr-1',
}

const mountDetail = async (id = 'open-webui') => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(ServiceDetailPage, { props: { id }, global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

// Mounts through a real RouterView (unlike mountDetail, which passes `id` as a static prop) so
// that navigating the router afterwards actually drives the component's `id` prop reactively,
// exactly like the app does — needed to exercise the CR-072 watch(() => props.id, ...) fix.
const mountRouted = async (id = 'open-webui') => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/services/:id', component: ServiceDetailPage, props: true },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  await router.push(`/services/${id}`)
  await router.isReady()
  const Host = defineComponent({ render: () => h(RouterView) })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ServiceDetailPage', () => {
  beforeEach(() => {
    vi.mocked(api.service).mockResolvedValue(service)
    vi.mocked(api.actions).mockResolvedValue([restartAction])
    vi.mocked(api.links).mockResolvedValue({ portainer: 'https://portainer.home.arpa' })
    vi.mocked(api.status).mockResolvedValue(status)
    vi.mocked(api.refresh).mockResolvedValue(status)
    vi.mocked(api.executions).mockResolvedValue({ items: [execution], total: 1, offset: 0, limit: 20 })
  })

  it('renders service detail, containers, actions and recent executions', async () => {
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain('Open WebUI')
    expect(wrapper.text()).toContain('Reiniciar')
    expect(wrapper.text()).toContain('Observabilidad')
    expect(wrapper.text()).toContain('restart')
  })

  it('executes a non-critical action directly and navigates to its execution page', async () => {
    vi.mocked(api.execute).mockResolvedValue({ ...execution, id: 'e-2' })
    const { wrapper, router } = await mountDetail()

    const executeBtn = wrapper.findAll('button').find((button) => button.text() === 'Ejecutar')
    await executeBtn?.trigger('click')
    await flushPromises()

    expect(api.execute).toHaveBeenCalledWith('open-webui', 'restart', {})
    expect(router.currentRoute.value.fullPath).toBe('/executions/e-2')
  })

  it('disables the execute button for a viewer without operate permission', async () => {
    const { wrapper } = await mountDetail()
    useAuthStore().selectDevRole('capataz-viewer')
    await flushPromises()

    const executeBtn = wrapper.findAll('button').find((button) => button.text() === 'Ejecutar')

    expect(executeBtn?.attributes('disabled')).toBeDefined()
  })

  it('shows the error banner when the service fails to load', async () => {
    vi.mocked(api.service).mockRejectedValueOnce(new Error('404'))
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain('No se pudo cargar el detalle del servicio.')
  })

  it('reacts to the :id route param changing without remounting (CR-072)', async () => {
    const { wrapper, router } = await mountRouted('open-webui')
    expect(wrapper.text()).toContain('Open WebUI')

    vi.mocked(api.service).mockResolvedValue(otherService)
    vi.mocked(api.actions).mockResolvedValue([])
    vi.mocked(api.status).mockResolvedValue(otherStatus)
    vi.mocked(api.refresh).mockResolvedValue(otherStatus)
    vi.mocked(api.executions).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20 })

    await router.push('/services/immich')
    await flushPromises()

    expect(wrapper.text()).toContain('Immich')
    expect(api.service).toHaveBeenCalledWith('immich')
  })

  it('refreshes the status when the refresh button is clicked', async () => {
    const { wrapper } = await mountDetail()
    vi.mocked(api.refresh).mockClear()

    await wrapper.get('[aria-label="Actualizar estado"]').trigger('click')
    await flushPromises()

    expect(api.refresh).toHaveBeenCalledWith('open-webui')
  })
})
