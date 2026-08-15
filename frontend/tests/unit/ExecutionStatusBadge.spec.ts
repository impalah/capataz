import { mount } from '@vue/test-utils'
import ExecutionStatusBadge from '@/components/ExecutionStatusBadge.vue'

describe('ExecutionStatusBadge', () => {
  it.each([
    ['queued', 'En cola'],
    ['running', 'En curso'],
    ['succeeded', 'Correcta'],
    ['failed', 'Fallida'],
    ['cancelled', 'Cancelada'],
    ['timed_out', 'Agotó tiempo'],
    ['rejected', 'Rechazada'],
  ] as const)('communicates %s with text as well as colour', (status, label) => {
    const wrapper = mount(ExecutionStatusBadge, { props: { status } })
    expect(wrapper.text()).toContain(label)
  })
})
