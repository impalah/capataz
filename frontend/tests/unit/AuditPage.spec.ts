import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AuditPage from '@/pages/AuditPage.vue'
import { api } from '@/api/capatazApi'
import type { AuditEvent } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({ api: { audits: vi.fn() } }))

const auditA: AuditEvent = {
  id: 'audit-1',
  timestamp: '2026-01-01T10:00:00.000Z',
  actor: 'ana.admin',
  actor_name: 'Ana Admin',
  action: 'execution.request',
  resource: 'e-001',
  outcome: 'success',
  request_id: 'req-1',
}
const auditB: AuditEvent = {
  id: 'audit-2',
  timestamp: '2026-01-01T09:00:00.000Z',
  actor: 'ana.admin',
  actor_name: 'Ana Admin',
  action: 'catalog.import',
  resource: 'catalog',
  outcome: 'denied',
}

const mountPage = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/audit', component: AuditPage },
      { path: '/executions/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/audit')
  await router.isReady()
  const wrapper = mount(AuditPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper }
}

describe('AuditPage', () => {
  it('loads and renders the audit log with a link to the related execution', async () => {
    vi.mocked(api.audits).mockResolvedValue({ items: [auditA, auditB], total: 2, offset: 0, limit: 20 })

    const { wrapper } = await mountPage()

    expect(api.audits).toHaveBeenCalledWith({ offset: 0, limit: 20 })
    expect(wrapper.text()).toContain('execution.request')
    expect(wrapper.find('a[href="/executions/e-001"]').exists()).toBe(true)
  })

  it("does not link a non-execution audit event's resource", async () => {
    vi.mocked(api.audits).mockResolvedValue({ items: [auditB], total: 1, offset: 0, limit: 20 })

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('catalog')
    expect(wrapper.find('a[href="/executions/catalog"]').exists()).toBe(false)
  })

  it('shows the error banner when the audit log fails to load', async () => {
    vi.mocked(api.audits).mockRejectedValueOnce(new Error('403'))

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('No se pudo cargar la auditoría.')
  })
})
