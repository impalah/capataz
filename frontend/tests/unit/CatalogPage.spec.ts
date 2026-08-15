import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { Notify } from 'quasar'
import CatalogPage from '@/pages/CatalogPage.vue'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import type { ActionDefinition, Service } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    services: vi.fn(),
    status: vi.fn(),
    actions: vi.fn(),
    importCatalog: vi.fn(),
    exportCatalog: vi.fn(),
    createService: vi.fn(),
    updateService: vi.fn(),
    deleteService: vi.fn(),
    createAction: vi.fn(),
    updateAction: vi.fn(),
    deleteAction: vi.fn(),
  },
}))

const service: Service = { id: 'open-webui', name: 'Open WebUI', group_name: 'IA', environment: 'homelab' }
const action: ActionDefinition = {
  id: 'a1',
  service_id: 'open-webui',
  key: 'restart',
  label: 'Reiniciar',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  config: { operation: 'restart', target: 'selected_containers' },
}

const mountPage = async () => {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/catalog', component: CatalogPage }],
  })
  await router.push('/catalog')
  await router.isReady()
  // QDialog portals its content and only mounts it while open; stubbing it inline keeps both
  // forms queryable without simulating the open interaction.
  const wrapper = mount(CatalogPage, {
    global: { plugins: [router], stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return { wrapper }
}

describe('CatalogPage', () => {
  beforeEach(() => {
    vi.mocked(api.services).mockResolvedValue({ items: [service], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.status).mockResolvedValue({ service_id: 'open-webui', status: 'healthy', containers: [] })
    vi.mocked(api.actions).mockResolvedValue([])
  })

  it('loads and lists catalog services on mount', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('Open WebUI')
  })

  it('dry-run validates the YAML and shows the resulting summary', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: true,
      valid: true,
      created: 1,
      updated: 0,
      errors: [],
    })
    const { wrapper } = await mountPage()

    const dryRunBtn = wrapper.findAll('button').find((button) => button.text().includes('Validar (dry-run)'))
    await dryRunBtn?.trigger('click')
    await flushPromises()

    expect(api.importCatalog).toHaveBeenCalledWith(expect.stringContaining('version: 1'), true)
    expect(wrapper.text()).toContain('Válido: 1 altas y 0 cambios previstos.')
  })

  it('shows per-field errors when the import is invalid', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: false,
      valid: false,
      created: 0,
      updated: 0,
      errors: [{ path: 'services[0].id', message: 'El identificador debe ser un slug válido.', line: 3 }],
    })
    const { wrapper } = await mountPage()

    const importBtn = wrapper.findAll('button').find((button) => button.text().includes('Importar'))
    await importBtn?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('El identificador debe ser un slug válido.')
  })

  it('exports the catalog and displays the returned YAML', async () => {
    vi.mocked(api.exportCatalog).mockResolvedValue({ yaml: 'version: 1\nservices:\n  - id: open-webui' })
    const { wrapper } = await mountPage()

    const exportBtn = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Generar exportación'))
    await exportBtn?.trigger('click')
    await flushPromises()

    expect((wrapper.get('textarea[readonly]').element as HTMLTextAreaElement).value).toContain('open-webui')
  })

  it('asks for confirmation before deleting a service, then deletes it on confirm (CR-070)', async () => {
    vi.mocked(api.deleteService).mockResolvedValue(undefined)
    const { wrapper } = await mountPage()
    vi.mocked(api.services).mockClear()

    await wrapper.get(`[aria-label="Eliminar ${service.name}"]`).trigger('click')
    await flushPromises()
    expect(api.deleteService).not.toHaveBeenCalled()

    await wrapper.get('[aria-label="Eliminar servicio"]').trigger('click')
    await flushPromises()

    expect(api.deleteService).toHaveBeenCalledWith('open-webui')
    expect(api.services).toHaveBeenCalled()
  })

  it('creates a new service from the dialog form', async () => {
    vi.mocked(api.createService).mockResolvedValue({ ...service, id: 'new-service' })
    const { wrapper } = await mountPage()

    const newServiceBtn = wrapper.findAll('button').find((button) => button.text().includes('Nuevo servicio'))
    await newServiceBtn?.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAllComponents({ name: 'QInput' })
    const idInput = inputs.find((input) => input.props('label') === 'ID (slug)')
    const nameInput = inputs.find((input) => input.props('label') === 'Nombre')
    await idInput?.vm.$emit('update:modelValue', 'new-service')
    await nameInput?.vm.$emit('update:modelValue', 'Nuevo servicio')

    const saveBtn = wrapper.findAll('button').find((button) => button.text() === 'Guardar')
    await saveBtn?.trigger('click')
    await flushPromises()

    expect(api.createService).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'new-service', name: 'Nuevo servicio' }),
    )
  })

  it('creates a new declarative action from the dialog form', async () => {
    vi.mocked(api.createAction).mockResolvedValue({
      id: 'a9',
      service_id: 'open-webui',
      key: 'restart',
      label: 'Reiniciar',
      action_type: 'portainer',
      risk_level: 'read',
      requires_confirmation: false,
      enabled: true,
      config: {},
    })
    const { wrapper } = await mountPage()

    const newActionBtn = wrapper.findAll('button').find((button) => button.text().includes('Nueva acción'))
    await newActionBtn?.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAllComponents({ name: 'QInput' })
    const keyInput = inputs.find((input) => input.props('label') === 'Clave (slug)')
    const labelInput = inputs.find((input) => input.props('label') === 'Etiqueta')
    await keyInput?.vm.$emit('update:modelValue', 'restart')
    await labelInput?.vm.$emit('update:modelValue', 'Reiniciar')

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'Guardar')
    await saveButtons[1]?.trigger('click')
    await flushPromises()

    expect(api.createAction).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({ key: 'restart', label: 'Reiniciar' }),
    )
  })

  it('blocks saving a new service with missing required fields and never calls the API (CR-076)', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.createService).mockClear()
    const newServiceBtn = wrapper.findAll('button').find((button) => button.text().includes('Nuevo servicio'))
    await newServiceBtn?.trigger('click')
    await flushPromises()

    const saveBtn = wrapper.findAll('button').find((button) => button.text() === 'Guardar')
    await saveBtn?.trigger('click')
    await flushPromises()

    expect(api.createService).not.toHaveBeenCalled()
  })

  it('blocks saving a new action with a missing label and never calls the API (CR-076)', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.createAction).mockClear()
    const newActionBtn = wrapper.findAll('button').find((button) => button.text().includes('Nueva acción'))
    await newActionBtn?.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAllComponents({ name: 'QInput' })
    const keyInput = inputs.find((input) => input.props('label') === 'Clave (slug)')
    await keyInput?.vm.$emit('update:modelValue', 'restart')

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'Guardar')
    await saveButtons[1]?.trigger('click')
    await flushPromises()

    expect(api.createAction).not.toHaveBeenCalled()
  })

  it('only offers the portainer action type until the form supports the others (CR-088)', async () => {
    const { wrapper } = await mountPage()
    const newActionBtn = wrapper.findAll('button').find((button) => button.text().includes('Nueva acción'))
    await newActionBtn?.trigger('click')
    await flushPromises()

    const typeSelect = wrapper
      .findAllComponents({ name: 'QSelect' })
      .find((select) => select.props('label') === 'Tipo')
    expect(typeSelect?.props('options')).toEqual([{ label: 'Portainer', value: 'portainer' }])
  })

  it('lists the actions declared for a service and edits one from the dialog (CR-071)', async () => {
    vi.mocked(api.actions).mockResolvedValue([action])
    vi.mocked(api.updateAction).mockResolvedValue(action)
    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('Reiniciar')

    await wrapper.get('[aria-label="Editar acción Reiniciar"]').trigger('click')
    await flushPromises()

    const inputs = wrapper.findAllComponents({ name: 'QInput' })
    const labelInput = inputs.find((input) => input.props('label') === 'Etiqueta')
    await labelInput?.vm.$emit('update:modelValue', 'Reiniciar contenedor')

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'Guardar')
    await saveButtons[saveButtons.length - 1]?.trigger('click')
    await flushPromises()

    expect(api.updateAction).toHaveBeenCalledWith(
      'open-webui',
      'restart',
      expect.objectContaining({ key: 'restart', label: 'Reiniciar contenedor' }),
    )
  })

  it('asks for confirmation before deleting an action, then deletes it on confirm (CR-071)', async () => {
    vi.mocked(api.actions).mockResolvedValue([action])
    vi.mocked(api.deleteAction).mockResolvedValue(undefined)
    const { wrapper } = await mountPage()

    await wrapper.get('[aria-label="Eliminar acción Reiniciar"]').trigger('click')
    await flushPromises()
    expect(api.deleteAction).not.toHaveBeenCalled()

    await wrapper.get('[aria-label="Eliminar acción"]').trigger('click')
    await flushPromises()

    expect(api.deleteAction).toHaveBeenCalledWith('open-webui', 'restart')
  })

  it('sends expected_version when editing a service and surfaces a 409 as a clear message (CR-091)', async () => {
    const versionedService: Service = { ...service, version: 3 }
    vi.mocked(api.services).mockResolvedValue({ items: [versionedService], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.updateService).mockRejectedValue(new ApiError(409, 'Version mismatch'))
    const { wrapper } = await mountPage()
    const notifySpy = vi.spyOn(Notify, 'create')

    await wrapper.get(`[aria-label="Editar ${service.name}"]`).trigger('click')
    await flushPromises()

    const saveBtn = wrapper.findAll('button').find((button) => button.text() === 'Guardar')
    await saveBtn?.trigger('click')
    await flushPromises()

    expect(api.updateService).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({ expected_version: 3 }),
    )
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({
        message: expect.stringContaining('se modificó mientras lo editabas'),
      }),
    )
  })

  it('shows an error notification when saving an action fails', async () => {
    vi.mocked(api.createAction).mockRejectedValue(new Error('boom'))
    const { wrapper } = await mountPage()
    const notifySpy = vi.spyOn(Notify, 'create')

    const newActionBtn = wrapper.findAll('button').find((button) => button.text().includes('Nueva acción'))
    await newActionBtn?.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAllComponents({ name: 'QInput' })
    const keyInput = inputs.find((input) => input.props('label') === 'Clave (slug)')
    const labelInput = inputs.find((input) => input.props('label') === 'Etiqueta')
    await keyInput?.vm.$emit('update:modelValue', 'restart')
    await labelInput?.vm.$emit('update:modelValue', 'Reiniciar')

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'Guardar')
    await saveButtons[1]?.trigger('click')
    await flushPromises()

    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: 'No se pudo guardar la acción.' }),
    )
  })

  it('shows an error notification when deleting an action fails', async () => {
    vi.mocked(api.actions).mockResolvedValue([action])
    vi.mocked(api.deleteAction).mockRejectedValue(new Error('boom'))
    const { wrapper } = await mountPage()
    const notifySpy = vi.spyOn(Notify, 'create')

    await wrapper.get('[aria-label="Eliminar acción Reiniciar"]').trigger('click')
    await flushPromises()
    await wrapper.get('[aria-label="Eliminar acción"]').trigger('click')
    await flushPromises()

    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: 'No se pudo eliminar la acción.' }),
    )
  })
})
