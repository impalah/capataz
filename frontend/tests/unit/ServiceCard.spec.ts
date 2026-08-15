import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import ServiceCard from '@/components/ServiceCard.vue'
import { api } from '@/api/capatazApi'
import type { ActionDefinition, Service, ServiceStatusResult } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    refresh: vi.fn(),
    execute: vi.fn(),
  },
}))

const service: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  description: 'Interfaz de modelos.',
  group_name: 'IA',
  environment: 'homelab',
  portainer_stack_name: 'ai-platform',
}
const status: ServiceStatusResult = {
  service_id: 'open-webui',
  status: 'healthy',
  checked_at: '2026-01-01T10:00:00.000Z',
  containers: [],
}
const restartAction: ActionDefinition = {
  id: 'a1',
  service_id: 'open-webui',
  key: 'restart',
  label: 'Reiniciar',
  icon: 'restart_alt',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  config: {},
}
const startAction: ActionDefinition = {
  id: 'a3',
  service_id: 'ollama-service',
  key: 'start',
  label: 'Iniciar',
  icon: 'play_arrow',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  unattended: true,
  config: {},
}
const backupAction: ActionDefinition = {
  id: 'a2',
  service_id: 'open-webui',
  key: 'backup',
  label: 'Copia de seguridad',
  icon: 'backup',
  action_type: 'ansible',
  risk_level: 'critical',
  requires_confirmation: true,
  enabled: true,
  config: {},
}
const confirmRequiredAction: ActionDefinition = {
  id: 'a4',
  service_id: 'open-webui',
  key: 'prune',
  label: 'Limpiar volúmenes',
  icon: 'delete_sweep',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: true,
  enabled: true,
  config: {},
}

interface CardProps {
  service: Service
  status?: ServiceStatusResult
  actions?: ActionDefinition[]
  canRefresh: boolean
}
const mountCard = async (props: CardProps) => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/services/:id', component: { template: '<div />' } },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  const wrapper = mount(ServiceCard, { props, global: { plugins: [router] } })
  await router.isReady()
  return { wrapper, router }
}

describe('ServiceCard', () => {
  beforeEach(() => {
    vi.mocked(api.refresh).mockReset()
    vi.mocked(api.execute).mockReset()
  })

  it('shows service information, including the stack, without a separate "ver servicio" button', async () => {
    const { wrapper } = await mountCard({ service, status, canRefresh: true })
    expect(wrapper.text()).toContain('Open WebUI')
    expect(wrapper.text()).toContain('Operativo')
    expect(wrapper.text()).toContain('ai-platform')
    expect(wrapper.find('a.card-link').attributes('href')).toBe('/services/open-webui')
    expect(wrapper.findAll('button').filter((b) => b.text() === 'Ver servicio')).toHaveLength(0)
  })

  it('falls back gracefully when status has not loaded yet', async () => {
    const { wrapper } = await mountCard({ service, canRefresh: false })
    expect(wrapper.text()).toContain('Desconocido')
  })

  it('refreshes status when the status badge is clicked and the user can operate', async () => {
    vi.mocked(api.refresh).mockResolvedValue({ ...status, status: 'degraded' })
    const { wrapper } = await mountCard({ service, status, canRefresh: true })
    await wrapper.get('[aria-label="Actualizar estado"]').trigger('click')
    await flushPromises()
    expect(api.refresh).toHaveBeenCalledWith('open-webui')
  })

  it('does not refresh on badge click for viewers without operate permission', async () => {
    const { wrapper } = await mountCard({ service, status, canRefresh: false })
    await wrapper.get('.card-status-trigger').trigger('click')
    await flushPromises()
    expect(api.refresh).not.toHaveBeenCalled()
  })

  it('executes a non-critical action directly and navigates to the execution', async () => {
    vi.mocked(api.execute).mockResolvedValue({
      id: 'exec-1',
      service_id: 'open-webui',
      service_id_snapshot: 'open-webui',
      action_definition_id: 'a1',
      requested_by_subject: 'tester',
      source: 'ui',
      params: {},
      status: 'queued',
      requested_at: '2026-01-01T10:00:00.000Z',
      correlation_id: 'corr-1',
    })
    const { wrapper, router } = await mountCard({
      service,
      status,
      actions: [restartAction],
      canRefresh: true,
    })
    await wrapper.get('button[aria-label="Reiniciar"]').trigger('click')
    await flushPromises()
    expect(api.execute).toHaveBeenCalledWith('open-webui', 'restart', {})
    expect(router.currentRoute.value.fullPath).toBe('/executions/exec-1')
  })

  it('stays on the page and refreshes status for an unattended action instead of navigating', async () => {
    vi.useFakeTimers()
    vi.mocked(api.execute).mockResolvedValue({
      id: 'exec-2',
      service_id: 'ollama-service',
      service_id_snapshot: 'ollama-service',
      action_definition_id: 'a3',
      requested_by_subject: 'tester',
      source: 'ui',
      params: {},
      status: 'queued',
      requested_at: '2026-01-01T10:00:00.000Z',
      correlation_id: 'corr-2',
    })
    vi.mocked(api.refresh).mockResolvedValue(status)
    const { wrapper, router } = await mountCard({
      service,
      status,
      actions: [startAction],
      canRefresh: true,
    })
    await wrapper.get('button[aria-label="Iniciar"]').trigger('click')
    await flushPromises()
    expect(api.execute).toHaveBeenCalledWith('open-webui', 'start', {})
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(api.refresh).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1500)
    expect(api.refresh).toHaveBeenCalledWith('open-webui')
    vi.useRealTimers()
  })

  it('opens the confirm dialog for a critical action instead of executing immediately', async () => {
    const { wrapper } = await mountCard({
      service,
      status,
      actions: [backupAction],
      canRefresh: true,
    })
    await wrapper.get('button[aria-label="Copia de seguridad"]').trigger('click')
    await flushPromises()
    expect(api.execute).not.toHaveBeenCalled()
    expect(wrapper.findComponent({ name: 'CriticalConfirmDialog' }).props('modelValue')).toBe(true)
  })

  it('opens the confirm dialog for a non-critical action that explicitly requires confirmation', async () => {
    const { wrapper } = await mountCard({
      service,
      status,
      actions: [confirmRequiredAction],
      canRefresh: true,
    })
    await wrapper.get('button[aria-label="Limpiar volúmenes"]').trigger('click')
    await flushPromises()
    expect(api.execute).not.toHaveBeenCalled()
    expect(wrapper.findComponent({ name: 'CriticalConfirmDialog' }).props('modelValue')).toBe(true)
  })
})
