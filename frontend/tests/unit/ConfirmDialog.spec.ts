import { mount } from '@vue/test-utils'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  it('emits confirm when the confirm button is clicked', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, title: 'Eliminar servicio', message: '¿Eliminar Open WebUI?' },
      global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
    })
    expect(wrapper.text()).toContain('¿Eliminar Open WebUI?')

    await wrapper.get('[data-testid="confirm-delete"]').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('uses a custom confirm label and forwards modelValue updates', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, title: 'Eliminar acción', message: 'msg', confirmLabel: 'Sí, eliminar' },
      global: { stubs: { QDialog: { name: 'QDialog', template: '<div><slot /></div>' } } },
    })
    expect(wrapper.get('[data-testid="confirm-delete"]').text()).toBe('Sí, eliminar')

    await wrapper.findComponent({ name: 'QDialog' }).vm.$emit('update:modelValue', false)

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
