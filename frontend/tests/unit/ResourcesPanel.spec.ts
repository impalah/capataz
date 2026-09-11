import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import ResourcesPanel from '@/components/catalog/ResourcesPanel.vue'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import type { Resource } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'

vi.mock('@/api/capatazApi', () => ({
  api: {
    resources: vi.fn(),
    createResource: vi.fn(),
    replaceResourceContent: vi.fn(),
    deleteResource: vi.fn(),
  },
}))

const resources: Resource[] = [
  {
    id: 'portainer_token',
    type: 'secret',
    description: 'Token de Portainer',
    fingerprint: 'abcdef123456',
    size: 24,
    source: { file: 'portainer_token' },
    version: 1,
    updated_at: '2026-09-10T10:00:00Z',
  },
  {
    id: 'kh',
    type: 'known_hosts',
    fingerprint: 'fedcba987654',
    size: 90,
    source: { env: 'KH_B64' },
    version: 1,
  },
  {
    id: 'dev_key',
    type: 'ssh_private_key',
    fingerprint: '0123456789ab',
    size: 400,
    source: { inline: true },
    version: 1,
  },
]

type Wrapper = Awaited<ReturnType<typeof mountPanel>>
const mountPanel = async () => {
  setActivePinia(createPinia())
  useCatalogStore().resources = resources
  const wrapper = mount(ResourcesPanel, {
    global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return wrapper
}
const component = (wrapper: Wrapper, name: string, label: string) =>
  wrapper.findAllComponents({ name }).find((candidate) => candidate.props('label') === label)
const set = async (
  target: { vm: { $emit: (event: string, value: unknown) => void } } | undefined,
  value: unknown,
) => {
  target?.vm.$emit('update:modelValue', value)
  await flushPromises()
}
const click = async (wrapper: Wrapper, text: string) => {
  await wrapper
    .findAll('button')
    .find((button) => button.text().includes(text))
    ?.trigger('click')
  await flushPromises()
}

describe('ResourcesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.resources).mockResolvedValue(resources)
  })

  it('lists metadata and provenance only', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    expect(text).toContain('portainer_token')
    expect(text).toContain('Secreto')
    expect(text).toContain('24 bytes')
    expect(text).toContain('abcdef123456')
    expect(text).toContain('fichero portainer_token')
    expect(text).toContain('variable KH_B64')
    expect(text).toContain('literal en el YAML')
    expect(text).toContain('Token de Portainer')
  })

  it('uploads pasted content base64-encoded and then forgets it', async () => {
    vi.mocked(api.createResource).mockResolvedValue(resources[0]!)
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo recurso')
    await set(component(wrapper, 'QInput', 'ID (slug)'), 'ssh_key')
    await set(component(wrapper, 'QSelect', 'Tipo'), 'ssh_private_key')
    await set(component(wrapper, 'QInput', 'O pega el contenido'), 'KEY-ñ\n')
    await click(wrapper, 'Guardar')

    expect(api.createResource).toHaveBeenCalledWith({
      id: 'ssh_key',
      type: 'ssh_private_key',
      description: null,
      content_base64: btoa(String.fromCharCode(...new TextEncoder().encode('KEY-ñ\n'))),
    })
    expect(component(wrapper, 'QInput', 'O pega el contenido')?.props('modelValue')).toBe('')
    expect(api.resources).toHaveBeenCalled()
  })

  it('uploads a selected file', async () => {
    vi.mocked(api.createResource).mockResolvedValue(resources[0]!)
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo recurso')
    await set(component(wrapper, 'QInput', 'ID (slug)'), 'kh2')
    await set(component(wrapper, 'QFile', 'Fichero'), new File(['host ssh-ed25519 AAAA'], 'known_hosts'))
    await click(wrapper, 'Guardar')

    expect(api.createResource).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'kh2', content_base64: btoa('host ssh-ed25519 AAAA') }),
    )
  })

  it('requires some content and enforces the 64 KiB limit before calling the API', async () => {
    const wrapper = await mountPanel()
    const notifySpy = vi.spyOn(Notify, 'create')
    await click(wrapper, 'Nuevo recurso')
    await set(component(wrapper, 'QInput', 'ID (slug)'), 'big')
    await click(wrapper, 'Guardar')
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Adjunta un fichero o pega el contenido.' }),
    )

    await set(component(wrapper, 'QInput', 'O pega el contenido'), 'x'.repeat(64 * 1024 + 1))
    await click(wrapper, 'Guardar')
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'El contenido supera 64 KiB.' }),
    )
    expect(api.createResource).not.toHaveBeenCalled()
  })

  it('replaces the content of an existing resource, keeping its id and type', async () => {
    vi.mocked(api.replaceResourceContent).mockResolvedValue(resources[0]!)
    const wrapper = await mountPanel()
    await wrapper.get('[aria-label="Reemplazar contenido de portainer_token"]').trigger('click')
    await flushPromises()

    expect(component(wrapper, 'QInput', 'ID (slug)')?.props('disable')).toBe(true)
    await set(component(wrapper, 'QInput', 'O pega el contenido'), 'new-token')
    await click(wrapper, 'Guardar')

    expect(api.replaceResourceContent).toHaveBeenCalledWith('portainer_token', {
      content_base64: btoa('new-token'),
      description: 'Token de Portainer',
    })
  })

  it('surfaces the API error when saving fails', async () => {
    vi.mocked(api.createResource).mockRejectedValue(new ApiError(422, 'content is not valid base64'))
    const wrapper = await mountPanel()
    const notifySpy = vi.spyOn(Notify, 'create')
    await click(wrapper, 'Nuevo recurso')
    await set(component(wrapper, 'QInput', 'ID (slug)'), 'x')
    await set(component(wrapper, 'QInput', 'O pega el contenido'), 'x')
    await click(wrapper, 'Guardar')
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'content is not valid base64' }),
    )
  })

  it('deletes a resource after confirmation, reporting a 409 when a connector uses it', async () => {
    vi.mocked(api.deleteResource).mockRejectedValueOnce(new ApiError(409, 'Resource in use by: portainer'))
    const wrapper = await mountPanel()
    const notifySpy = vi.spyOn(Notify, 'create')
    await wrapper.get('[aria-label="Eliminar recurso portainer_token"]').trigger('click')
    await flushPromises()
    await wrapper.get('[aria-label="Eliminar recurso"]').trigger('click')
    await flushPromises()
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Resource in use by: portainer' }),
    )

    vi.mocked(api.deleteResource).mockResolvedValueOnce(undefined)
    await wrapper.get('[aria-label="Eliminar recurso"]').trigger('click')
    await flushPromises()
    expect(api.deleteResource).toHaveBeenLastCalledWith('portainer_token')
    expect(notifySpy).toHaveBeenCalledWith(expect.objectContaining({ message: 'Recurso eliminado.' }))
  })
})
