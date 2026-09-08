import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ServiceCard from '@/components/ServiceCard.vue'
import type { Service, ServiceStatusResult } from '@/api/types'

const service: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  description: 'Interfaz de modelos.',
  group_name: 'IA',
  environment: 'homelab',
  portainer_stack_name: 'ai-platform',
  service_url: 'https://open-webui.home.arpa',
}
const status: ServiceStatusResult = {
  service_id: 'open-webui',
  status: 'healthy',
  checked_at: '2026-01-01T10:00:00.000Z',
  containers: [],
  error: 'timed out',
}

interface CardProps {
  service: Service
  status?: ServiceStatusResult
}
const mountCard = async (props: CardProps) => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/services/:id', component: { template: '<div />' } }],
  })
  const wrapper = mount(ServiceCard, { props, global: { plugins: [router] } })
  await router.isReady()
  return { wrapper, router }
}

describe('ServiceCard', () => {
  it('shows only the name and status, none of description/group/environment/stack', async () => {
    const { wrapper } = await mountCard({ service, status })
    expect(wrapper.text()).toContain('Open WebUI')
    expect(wrapper.text()).toContain('Operativo')
    expect(wrapper.text()).not.toContain('Interfaz de modelos.')
    expect(wrapper.text()).not.toContain('IA')
    expect(wrapper.text()).not.toContain('homelab')
    expect(wrapper.text()).not.toContain('ai-platform')
  })

  it('renders no action buttons', async () => {
    const { wrapper } = await mountCard({ service, status })
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('is a single full-card link to the service detail page, with no other click targets', async () => {
    const { wrapper } = await mountCard({ service, status })
    const link = wrapper.get('a.card-link')
    expect(link.attributes('href')).toBe('/services/open-webui')
    expect(wrapper.findAll('a')).toHaveLength(1)
  })

  it('renders the icon as plain, non-interactive markup even when the service has a service_url', async () => {
    const { wrapper } = await mountCard({ service, status })
    expect(wrapper.get('.card-icon i.q-icon').text()).toBe('dns')
    const icon = wrapper.get('.card-icon')
    expect(icon.attributes('role')).toBeUndefined()
    expect(icon.attributes('tabindex')).toBeUndefined()
    expect(icon.attributes('onclick')).toBeUndefined()
  })

  it('renders the status badge as plain, non-interactive markup', async () => {
    const { wrapper } = await mountCard({ service, status })
    const trigger = wrapper.get('.card-status-trigger')
    expect(trigger.attributes('role')).toBeUndefined()
    expect(trigger.attributes('tabindex')).toBeUndefined()
    expect(trigger.attributes('aria-label')).toBeUndefined()
  })

  it('falls back gracefully when status has not loaded yet', async () => {
    const { wrapper } = await mountCard({ service })
    expect(wrapper.text()).toContain('Desconocido')
  })

  it('renders the status row before the icon+title row', async () => {
    const { wrapper } = await mountCard({ service, status })
    const rows = wrapper.findAll('.card-row-status, .card-row-title')
    expect(rows.map((row) => row.classes())).toEqual([['card-row-status'], ['card-row-title']])
  })

  it('applies no state class when the service is healthy', async () => {
    const { wrapper } = await mountCard({ service, status })
    expect(wrapper.get('.service-card').classes()).not.toContain('service-card--unknown')
    expect(wrapper.get('.service-card').classes()).not.toContain('service-card--down')
  })

  it('mutes the card background when the status is unknown or has not loaded yet', async () => {
    const { wrapper: withoutStatus } = await mountCard({ service })
    expect(withoutStatus.get('.service-card').classes()).toContain('service-card--unknown')

    const { wrapper: withUnknownStatus } = await mountCard({
      service,
      status: { ...status, status: 'unknown' },
    })
    expect(withUnknownStatus.get('.service-card').classes()).toContain('service-card--unknown')
  })

  it('flags the card red when the service is down', async () => {
    const { wrapper } = await mountCard({ service, status: { ...status, status: 'down' } })
    expect(wrapper.get('.service-card').classes()).toContain('service-card--down')
  })

  it('renders a grid cell (label + value) for each catalog-declared metric', async () => {
    const { wrapper } = await mountCard({
      service,
      status: {
        ...status,
        metrics: [
          { label: 'CPU', value: 12.5 },
          { label: 'Memoria', value: 512 },
        ],
      },
    })
    const cells = wrapper.findAll('.metric-cell')
    expect(cells.map((cell) => cell.get('.metric-label').text())).toEqual(['CPU', 'Memoria'])
    expect(cells.map((cell) => cell.get('.metric-value').text())).toEqual(['12.5', '512'])
  })

  it('shows a placeholder dash for a metric whose value is null', async () => {
    const { wrapper } = await mountCard({
      service,
      status: { ...status, metrics: [{ label: 'CPU', value: null }] },
    })
    expect(wrapper.get('.metric-value').text()).toBe('—')
  })

  it('renders no metrics row when the service declares none', async () => {
    const { wrapper } = await mountCard({ service, status })
    expect(wrapper.find('.card-row-metrics').exists()).toBe(false)
  })
})
