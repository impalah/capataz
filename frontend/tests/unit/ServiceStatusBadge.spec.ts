import { mount } from '@vue/test-utils'
import ServiceStatusBadge from '@/components/ServiceStatusBadge.vue'

describe('ServiceStatusBadge', () => {
  it.each([
    ['healthy', 'Operativo'],
    ['degraded', 'Degradado'],
    ['down', 'Caído'],
    ['maintenance', 'Mantenimiento'],
    ['unknown', 'Desconocido'],
  ] as const)('communicates %s with text as well as colour', (status, label) => {
    const wrapper = mount(ServiceStatusBadge, { props: { status } })
    expect(wrapper.text()).toContain(label)
  })
})
