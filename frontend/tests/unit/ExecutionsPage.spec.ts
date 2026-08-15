import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ExecutionsPage from '@/pages/ExecutionsPage.vue'
import { api } from '@/api/capatazApi'
import type { Execution } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({ api: { executions: vi.fn() } }))

const execA: Execution = {
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
const execB: Execution = {
  id: 'e-2',
  service_id: 'immich',
  service_id_snapshot: 'immich',
  action_definition_id: 'a2',
  action_key: 'backup',
  requested_by_subject: 'ana',
  source: 'ui',
  params: {},
  status: 'failed',
  requested_at: '2026-01-01T09:00:00.000Z',
  correlation_id: 'corr-2',
}

const mountPage = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/executions', component: ExecutionsPage },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/executions')
  await router.isReady()
  const wrapper = mount(ExecutionsPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ExecutionsPage', () => {
  beforeEach(() => {
    vi.mocked(api.executions).mockResolvedValue({ items: [execA, execB], total: 2, offset: 0, limit: 10 })
  })

  it('loads the first page of executions on mount and links each row to its detail page', async () => {
    const { wrapper } = await mountPage()
    expect(api.executions).toHaveBeenCalledWith({ offset: 0, limit: 10 })
    expect(wrapper.text()).toContain('e-1')
    expect(wrapper.find('a[href="/executions/e-1"]').exists()).toBe(true)
  })

  it('filters the visible rows by the search text', async () => {
    const { wrapper } = await mountPage()
    await wrapper.get('.table-filter input').setValue('immich')
    await flushPromises()

    expect(wrapper.text()).toContain('e-2')
    expect(wrapper.text()).not.toContain('e-1')
  })

  it('shows the empty state when nothing matches the filter', async () => {
    const { wrapper } = await mountPage()
    await wrapper.get('.table-filter input').setValue('nonexistent')
    await flushPromises()

    expect(wrapper.text()).toContain('No hay ejecuciones que coincidan con el filtro.')
  })

  it('reloads the current page when the refresh button is clicked', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.executions).mockClear()

    await wrapper.get('[aria-label="Actualizar"]').trigger('click')
    await flushPromises()

    expect(api.executions).toHaveBeenCalledWith({ offset: 0, limit: 10 })
  })
})
