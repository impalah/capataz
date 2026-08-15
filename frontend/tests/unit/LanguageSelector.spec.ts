import { mount } from '@vue/test-utils'
import LanguageSelector from '@/components/LanguageSelector.vue'
import { i18n } from '@/i18n'

describe('LanguageSelector', () => {
  afterEach(() => {
    i18n.global.locale.value = 'es-ES'
    localStorage.clear()
  })

  it('shows the current locale as a short code', async () => {
    i18n.global.locale.value = 'fr-FR'
    const wrapper = mount(LanguageSelector, {
      global: { stubs: { QMenu: { template: '<div><slot /></div>' } } },
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('FR')
  })

  it('lists all supported languages and switches locale + persists the choice on click', async () => {
    const wrapper = mount(LanguageSelector, {
      global: { stubs: { QMenu: { template: '<div><slot /></div>' } } },
    })

    expect(wrapper.text()).toContain('Deutsch (Deutschland)')
    expect(wrapper.text()).toContain('Italiano (Italia)')

    const deItem = wrapper.findAll('.q-item').find((item) => item.text().includes('Deutsch (Deutschland)'))
    await deItem?.trigger('click')

    expect(i18n.global.locale.value).toBe('de-DE')
    expect(localStorage.getItem('capataz.locale')).toBe('de-DE')
  })
})
