import { mount } from '@vue/test-utils'
import CriticalConfirmDialog from '@/components/CriticalConfirmDialog.vue'
import type { ActionDefinition, Service } from '@/api/types'
const action: ActionDefinition = {
  id: 'backup',
  service_id: 'open-webui',
  key: 'backup',
  label: 'Copia de seguridad',
  action_type: 'ansible',
  risk_level: 'critical',
  requires_confirmation: true,
  enabled: true,
  config: {},
}
const service: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  group_name: 'IA',
  environment: 'homelab',
}

describe('CriticalConfirmDialog', () => {
  it('requires a reason before the critical action is confirmed', async () => {
    const wrapper = mount(CriticalConfirmDialog, {
      props: { modelValue: true, action, service },
      global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
    })
    const button = wrapper.get('[data-testid="critical-confirm"]').element as HTMLButtonElement
    expect(button.disabled).toBe(true)
    const textarea = wrapper.get('[data-testid="critical-reason"]').element as HTMLTextAreaElement
    textarea.value = 'Mantenimiento programado'
    textarea.dispatchEvent(new Event('input'))
    await wrapper.vm.$nextTick()
    expect(button.disabled).toBe(false)
    button.click()
    expect(wrapper.emitted('confirm')).toEqual([['Mantenimiento programado']])
  })
})
