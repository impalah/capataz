import { mount } from '@vue/test-utils'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'

describe('AutoRefreshSelect', () => {
  it('reflects the current interval and emits an update when a new option is chosen', async () => {
    const wrapper = mount(AutoRefreshSelect, { props: { modelValue: 30000 } })
    expect(wrapper.props('modelValue')).toBe(30000)

    await wrapper.findComponent({ name: 'QSelect' }).vm.$emit('update:modelValue', 5000)

    expect(wrapper.emitted('update:modelValue')).toEqual([[5000]])
  })

  it('disables the select when disable is true', () => {
    const wrapper = mount(AutoRefreshSelect, { props: { modelValue: 0, disable: true } })
    expect(wrapper.findComponent({ name: 'QSelect' }).props('disable')).toBe(true)
  })
})
