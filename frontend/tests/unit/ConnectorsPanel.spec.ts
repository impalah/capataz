import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import ConnectorsPanel from '@/components/catalog/ConnectorsPanel.vue'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import type { Connector, Resource } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'

vi.mock('@/api/capatazApi', () => ({
  api: {
    connectors: vi.fn(),
    createConnector: vi.fn(),
    updateConnector: vi.fn(),
    deleteConnector: vi.fn(),
  },
}))

const connectors: Connector[] = [
  {
    id: 'portainer',
    type: 'portainer',
    config: { url: 'https://portainer.home.arpa', token: 'portainer_token', verify_tls: true },
    capabilities: ['status', 'actions'],
    version: 3,
  },
  {
    id: 'ssh_mole',
    type: 'ssh',
    description: 'Mole',
    config: { host: 'mole.home.arpa', port: 22, user: 'capataz', private_key: 'ssh_key', known_hosts: 'kh' },
    capabilities: ['actions'],
    version: 1,
  },
]
const resources: Resource[] = [
  {
    id: 'portainer_token',
    type: 'secret',
    description: 'Token de Portainer',
    fingerprint: 'abcdef123456',
    size: 24,
    source: { file: 'portainer_token' },
    version: 1,
  },
  {
    id: 'ssh_key',
    type: 'ssh_private_key',
    fingerprint: '0123456789ab',
    size: 400,
    source: { upload: true },
    version: 1,
  },
  {
    id: 'kh',
    type: 'known_hosts',
    fingerprint: 'fedcba987654',
    size: 90,
    source: { upload: true },
    version: 1,
  },
]

type Wrapper = Awaited<ReturnType<typeof mountPanel>>
const mountPanel = async () => {
  setActivePinia(createPinia())
  const catalog = useCatalogStore()
  catalog.connectors = connectors
  catalog.resources = resources
  const wrapper = mount(ConnectorsPanel, {
    global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return wrapper
}
const input = (wrapper: Wrapper, label: string) =>
  wrapper.findAllComponents({ name: 'QInput' }).find((component) => component.props('label') === label)
const select = (wrapper: Wrapper, label: string) =>
  wrapper.findAllComponents({ name: 'QSelect' }).find((component) => component.props('label') === label)
const set = async (
  component: { vm: { $emit: (event: string, value: unknown) => void } } | undefined,
  value: unknown,
) => {
  component?.vm.$emit('update:modelValue', value)
  await flushPromises()
}
const click = async (wrapper: Wrapper, text: string) => {
  await wrapper
    .findAll('button')
    .find((button) => button.text().includes(text))
    ?.trigger('click')
  await flushPromises()
}

describe('ConnectorsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.connectors).mockResolvedValue(connectors)
  })

  it('lists each connector with its type, target and capabilities', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('https://portainer.home.arpa')
    expect(wrapper.text()).toContain('capataz@mole.home.arpa')
    expect(wrapper.text()).toContain('Mole')
    expect(wrapper.text()).toContain('Estado')
    expect(wrapper.text()).toContain('Acciones')
  })

  it('shows an empty state without connectors', async () => {
    setActivePinia(createPinia())
    const wrapper = mount(ConnectorsPanel, {
      global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('No hay conectores definidos.')
  })

  it('creates a Portainer connector, offering only secret resources for its token', async () => {
    vi.mocked(api.createConnector).mockResolvedValue(connectors[0]!)
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo conector')

    expect(select(wrapper, 'Token')?.props('options')).toEqual([
      { label: 'portainer_token — Token de Portainer', value: 'portainer_token' },
    ])
    await set(input(wrapper, 'ID (slug)'), 'portainer_main')
    await set(input(wrapper, 'URL'), 'https://p.home.arpa')
    await set(select(wrapper, 'Token'), 'portainer_token')
    await click(wrapper, 'Guardar')

    expect(api.createConnector).toHaveBeenCalledWith({
      id: 'portainer_main',
      type: 'portainer',
      description: null,
      config: { url: 'https://p.home.arpa', token: 'portainer_token', verify_tls: true },
    })
    expect(api.connectors).toHaveBeenCalled()
  })

  it('builds an SSH connector config with its default port and key resources', async () => {
    vi.mocked(api.createConnector).mockResolvedValue(connectors[1]!)
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo conector')
    await set(select(wrapper, 'Tipo'), 'ssh')

    expect(input(wrapper, 'URL')).toBeUndefined()
    await set(input(wrapper, 'ID (slug)'), 'ssh_nas')
    await set(input(wrapper, 'Host'), 'nas.home.arpa')
    await set(input(wrapper, 'Usuario'), 'capataz')
    await set(select(wrapper, 'Clave privada SSH'), 'ssh_key')
    await set(select(wrapper, 'known_hosts'), 'kh')
    await click(wrapper, 'Guardar')

    expect(api.createConnector).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'ssh',
        config: {
          host: 'nas.home.arpa',
          port: 22,
          user: 'capataz',
          private_key: 'ssh_key',
          known_hosts: 'kh',
        },
      }),
    )
  })

  it('splits the http connector host suffixes into a list', async () => {
    vi.mocked(api.createConnector).mockResolvedValue(connectors[0]!)
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo conector')
    await set(select(wrapper, 'Tipo'), 'http')
    await set(input(wrapper, 'ID (slug)'), 'http')
    await set(input(wrapper, 'Sufijos de host permitidos'), '.home.arpa, .lan,')
    await click(wrapper, 'Guardar')

    expect(api.createConnector).toHaveBeenCalledWith(
      expect.objectContaining({
        config: {
          allowed_host_suffixes: ['.home.arpa', '.lan'],
          verify_tls: true,
          default_timeout_seconds: 5,
        },
      }),
    )
  })

  it('blocks saving without the required fields', async () => {
    const wrapper = await mountPanel()
    await click(wrapper, 'Nuevo conector')
    await click(wrapper, 'Guardar')
    expect(api.createConnector).not.toHaveBeenCalled()
  })

  it('edits a connector with its version as the optimistic-concurrency guard', async () => {
    vi.mocked(api.updateConnector).mockResolvedValue(connectors[0]!)
    const wrapper = await mountPanel()
    await wrapper.get('[aria-label="Editar conector portainer"]').trigger('click')
    await flushPromises()

    expect(input(wrapper, 'ID (slug)')?.props('disable')).toBe(true)
    await set(input(wrapper, 'URL'), 'https://portainer2.home.arpa')
    await click(wrapper, 'Guardar')

    expect(api.updateConnector).toHaveBeenCalledWith(
      'portainer',
      {
        id: 'portainer',
        type: 'portainer',
        description: null,
        config: { url: 'https://portainer2.home.arpa', token: 'portainer_token', verify_tls: true },
      },
      3,
    )
  })

  it('reports a version conflict when the connector changed meanwhile', async () => {
    vi.mocked(api.updateConnector).mockRejectedValue(new ApiError(409, 'Version mismatch'))
    const wrapper = await mountPanel()
    const notifySpy = vi.spyOn(Notify, 'create')
    await wrapper.get('[aria-label="Editar conector portainer"]').trigger('click')
    await flushPromises()
    await click(wrapper, 'Guardar')

    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('se modificó mientras lo editabas') }),
    )
  })

  it('deletes a connector after confirmation and surfaces the API detail when it is in use', async () => {
    vi.mocked(api.deleteConnector).mockRejectedValueOnce(new ApiError(409, 'Connector in use by: open-webui'))
    const wrapper = await mountPanel()
    const notifySpy = vi.spyOn(Notify, 'create')

    await wrapper.get('[aria-label="Eliminar conector portainer"]').trigger('click')
    await flushPromises()
    expect(api.deleteConnector).not.toHaveBeenCalled()
    await wrapper.get('[aria-label="Eliminar conector"]').trigger('click')
    await flushPromises()
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Connector in use by: open-webui' }),
    )

    vi.mocked(api.deleteConnector).mockResolvedValueOnce(undefined)
    await wrapper.get('[aria-label="Eliminar conector"]').trigger('click')
    await flushPromises()
    expect(api.deleteConnector).toHaveBeenLastCalledWith('portainer')
    expect(notifySpy).toHaveBeenCalledWith(expect.objectContaining({ message: 'Conector eliminado.' }))
  })
})
