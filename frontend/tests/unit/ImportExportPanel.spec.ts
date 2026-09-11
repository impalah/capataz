import { mount, flushPromises } from '@vue/test-utils'
import { Notify } from 'quasar'
import ImportExportPanel from '@/components/catalog/ImportExportPanel.vue'
import { api } from '@/api/capatazApi'

vi.mock('@/api/capatazApi', () => ({
  api: { importCatalog: vi.fn(), exportCatalog: vi.fn() },
}))

const click = async (wrapper: ReturnType<typeof mount>, text: string) => {
  await wrapper
    .findAll('button')
    .find((button) => button.text().includes(text))
    ?.trigger('click')
  await flushPromises()
}

describe('ImportExportPanel', () => {
  it('dry-runs a v2 catalog and shows the per-kind counts and warnings', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: true,
      valid: true,
      created: 1,
      updated: 0,
      errors: [],
      warnings: [{ path: 'resources[0].source', message: 'inline resource content', line: 4 }],
      counts: { resources: { created: 1, updated: 0, unchanged: 2 }, services: { created: 1, updated: 0 } },
    })
    const wrapper = mount(ImportExportPanel)
    await click(wrapper, 'Validar (dry-run)')

    expect(api.importCatalog).toHaveBeenCalledWith(expect.stringContaining('version: 2'), true)
    expect(wrapper.text()).toContain('Válido: 1 altas y 0 cambios previstos.')
    expect(wrapper.text()).toContain('Recursos: 1 altas, 0 cambios')
    expect(wrapper.text()).toContain('Avisos')
    expect(wrapper.text()).toContain('resources[0].source (línea 4): inline resource content')
    expect(wrapper.emitted('imported')).toBeUndefined()
  })

  it('shows per-field errors and does not report an import when invalid', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: false,
      valid: false,
      created: 0,
      updated: 0,
      errors: [{ path: 'services[0].runtime.connector', message: "unknown connector 'nope'", line: 9 }],
    })
    const wrapper = mount(ImportExportPanel)
    await click(wrapper, 'Importar')

    expect(wrapper.text()).toContain("unknown connector 'nope'")
    expect(wrapper.emitted('imported')).toBeUndefined()
  })

  it('emits imported after a valid import', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: false,
      valid: true,
      created: 0,
      updated: 2,
      errors: [],
    })
    const wrapper = mount(ImportExportPanel)
    await click(wrapper, 'Importar')
    expect(wrapper.emitted('imported')).toHaveLength(1)
  })

  it('notifies when the API rejects the import request', async () => {
    vi.mocked(api.importCatalog).mockRejectedValue(new Error('boom'))
    const wrapper = mount(ImportExportPanel)
    const notifySpy = vi.spyOn(Notify, 'create')
    await click(wrapper, 'Validar (dry-run)')
    await click(wrapper, 'Importar')
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'No se pudo validar el catálogo.' }),
    )
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'La importación no fue aceptada.' }),
    )
  })

  it('exports the catalog and displays the returned YAML', async () => {
    vi.mocked(api.exportCatalog).mockResolvedValue({ yaml: 'version: 2\nservices:\n  - id: open-webui' })
    const wrapper = mount(ImportExportPanel)
    await click(wrapper, 'Generar exportación')
    expect((wrapper.get('textarea[readonly]').element as HTMLTextAreaElement).value).toContain('open-webui')
  })
})
