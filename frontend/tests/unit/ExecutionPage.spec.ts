import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { defineComponent, h } from 'vue'
import ExecutionPage from '@/pages/ExecutionPage.vue'
import { api } from '@/api/capatazApi'
import type { Execution, ExecutionEvent } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({ api: { execution: vi.fn(), events: vi.fn() } }))

const runningExecution: Execution = {
  id: 'e-1',
  service_id: 'open-webui',
  service_id_snapshot: 'open-webui',
  action_definition_id: 'a1',
  action_key: 'restart',
  requested_by_subject: 'ana',
  source: 'ui',
  params: {},
  status: 'running',
  requested_at: '2026-01-01T10:00:00.000Z',
  correlation_id: 'corr-1',
}
const events: ExecutionEvent[] = [
  {
    id: 'ev-1',
    execution_id: 'e-1',
    sequence: 1,
    timestamp: '2026-01-01T10:00:00.000Z',
    level: 'info',
    event_type: 'execution_started',
    message: 'Comenzó.',
  },
]

const mountPage = async (id = 'e-1') => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/executions', component: { template: '<div />' } },
      { path: '/executions/:id', component: ExecutionPage, props: true },
    ],
  })
  await router.push(`/executions/${id}`)
  await router.isReady()
  const wrapper = mount(ExecutionPage, { props: { id }, global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

// Mounts through a real RouterView (unlike mountPage, which passes `id` as a static prop) so that
// navigating the router afterwards actually drives the component's `id` prop reactively, exactly
// like the app does — needed to exercise the CR-072 watch(() => props.id, ...) fix.
const mountRouted = async (id = 'e-1') => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/executions', component: { template: '<div />' } },
      { path: '/executions/:id', component: ExecutionPage, props: true },
    ],
  })
  await router.push(`/executions/${id}`)
  await router.isReady()
  const Host = defineComponent({ render: () => h(RouterView) })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ExecutionPage', () => {
  beforeEach(() => {
    vi.mocked(api.execution).mockResolvedValue(runningExecution)
    vi.mocked(api.events).mockResolvedValue(events)
  })

  it('renders the execution timeline and detail fields', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('Ejecución e-1')
    expect(wrapper.text()).toContain('Comenzó.')
    expect(wrapper.text()).toContain('corr-1')
  })

  it('never renders a Cancelar button (CR-073: safe worker cancellation is not supported in V1)', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.findAll('button').find((button) => button.text() === 'Cancelar')).toBeUndefined()
  })

  it('shows the error banner when the execution fails to load', async () => {
    vi.mocked(api.execution).mockRejectedValueOnce(new Error('404'))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('No se pudo cargar la ejecución.')
  })

  it('reacts to the :id route param changing without remounting (CR-072)', async () => {
    const { wrapper, router } = await mountRouted('e-1')
    expect(wrapper.text()).toContain('Ejecución e-1')

    vi.mocked(api.execution).mockResolvedValue({
      ...runningExecution,
      id: 'e-2',
      service_id_snapshot: 'immich',
      correlation_id: 'corr-2',
    })
    vi.mocked(api.events).mockResolvedValue(events)

    await router.push('/executions/e-2')
    await flushPromises()

    expect(wrapper.text()).toContain('Ejecución e-2')
    expect(api.execution).toHaveBeenCalledWith('e-2')
  })

  it('manual refresh re-polls detail and events', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.execution).mockClear()
    vi.mocked(api.events).mockClear()

    await wrapper.get('[aria-label="Actualizar estado"]').trigger('click')
    await flushPromises()

    expect(api.execution).toHaveBeenCalledWith('e-1')
    expect(api.events).toHaveBeenCalledWith('e-1')
  })
})
