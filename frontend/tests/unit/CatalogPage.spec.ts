import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { Notify } from 'quasar'
import type { MockInstance } from 'vitest'
import CatalogPage from '@/pages/CatalogPage.vue'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import type { ActionDefinition, Connector, Service } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    services: vi.fn(),
    refresh: vi.fn(),
    actions: vi.fn(),
    connectors: vi.fn(),
    resources: vi.fn(),
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

const connectors: Connector[] = [
  {
    id: 'portainer',
    type: 'portainer',
    config: { url: 'https://portainer.home.arpa', token: 'portainer_token' },
    capabilities: ['status', 'actions'],
    version: 1,
  },
  { id: 'http', type: 'http', config: {}, capabilities: ['health'], version: 1 },
  {
    id: 'grafana',
    type: 'grafana',
    config: { url: 'https://grafana.home.arpa' },
    capabilities: ['dashboards'],
    version: 1,
  },
  { id: 'loki', type: 'loki', config: { url: 'https://loki.home.arpa' }, capabilities: ['logs'], version: 1 },
  {
    id: 'prometheus',
    type: 'prometheus',
    config: { url: 'http://prometheus.home.arpa:9090' },
    capabilities: ['metrics'],
    version: 1,
  },
  {
    id: 'ansible',
    type: 'ansible',
    config: { inventory: 'inventories/homelab.yml', private_key: 'k', known_hosts: 'kh' },
    capabilities: ['actions'],
    version: 1,
  },
  {
    id: 'ssh_mole',
    type: 'ssh',
    config: { host: 'mole.home.arpa', user: 'capataz', private_key: 'k', known_hosts: 'kh' },
    capabilities: ['actions'],
    version: 1,
  },
]
const service: Service = { id: 'open-webui', name: 'Open WebUI', group_name: 'IA', environment: 'homelab' }
const richService: Service = {
  id: 'open-webui',
  name: 'Open WebUI',
  group_name: 'IA',
  environment: 'homelab',
  version: 2,
  tags: ['ia'],
  runtime: {
    connector: 'portainer',
    environment_id: '3',
    stack_name: 'ai',
    aggregation: 'all_required',
    containers: [{ name: 'app', required: true, critical: false }],
  },
  observability: {
    health: {
      connector: 'http',
      url: 'https://open-webui.home.arpa/health',
      method: 'GET',
      expected_status: 200,
      timeout_seconds: 5,
    },
    dashboards: [
      {
        label: 'grafana',
        connector: 'grafana',
        uid: 'dash-1',
        slug: 'open-webui',
        variables: { 'var-service': 'open-webui' },
      },
    ],
    logs: { connector: 'loki', query: '{compose_service="open-webui"}' },
    metrics: [],
  },
}
const swarmService: Service = {
  id: 'authentik',
  name: 'Authentik',
  group_name: 'Seguridad',
  environment: 'homelab',
  version: 5,
  runtime: {
    connector: 'portainer',
    environment_id: '7',
    stack_name: 'authentik',
    aggregation: 'all_required',
    services: [{ name: 'authentik-server', replicas: 1, required: true, critical: false }],
  },
}
const action: ActionDefinition = {
  id: 'a1',
  service_id: 'open-webui',
  key: 'restart',
  label: 'Reiniciar',
  action_type: 'portainer',
  connector: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  config: { operation: 'restart', target: 'selected_containers' },
}

type Wrapper = Awaited<ReturnType<typeof mountPage>>['wrapper']
const mountPage = async (beforeFlush?: () => void) => {
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
  // Quasar's Notify plugin re-assigns Notify.create on every mount, so a spy must be created
  // after mount() — and before flushing, to see notifications fired while the page loads.
  beforeFlush?.()
  await flushPromises()
  return { wrapper }
}
const inputs = (wrapper: Wrapper, label: string) =>
  wrapper.findAllComponents({ name: 'QInput' }).filter((input) => input.props('label') === label)
const selects = (wrapper: Wrapper, label: string) =>
  wrapper.findAllComponents({ name: 'QSelect' }).filter((select) => select.props('label') === label)
const toggles = (wrapper: Wrapper, label: string) =>
  wrapper.findAllComponents({ name: 'QToggle' }).filter((toggle) => toggle.props('label') === label)
const button = (wrapper: Wrapper, text: string) =>
  wrapper.findAll('button').find((candidate) => candidate.text().includes(text))
const set = async (
  component: { vm: { $emit: (event: string, value: unknown) => void } } | undefined,
  value: unknown,
) => {
  component?.vm.$emit('update:modelValue', value)
  await flushPromises()
}
const click = async (wrapper: Wrapper, text: string) => {
  await button(wrapper, text)?.trigger('click')
  await flushPromises()
}
// Both dialogs are always rendered (the QDialog stub ignores v-model): the service dialog's
// "Guardar" comes first in DOM order, the action dialog's second.
const saveService = async (wrapper: Wrapper) => {
  await wrapper
    .findAll('button')
    .filter((candidate) => candidate.text() === 'Guardar')[0]
    ?.trigger('click')
  await flushPromises()
}
const saveAction = async (wrapper: Wrapper) => {
  await wrapper
    .findAll('button')
    .filter((candidate) => candidate.text() === 'Guardar')[1]
    ?.trigger('click')
  await flushPromises()
}

describe('CatalogPage', () => {
  beforeEach(() => {
    vi.mocked(api.services).mockResolvedValue({ items: [service], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.refresh).mockResolvedValue({ service_id: 'open-webui', status: 'healthy', containers: [] })
    vi.mocked(api.actions).mockResolvedValue([])
    vi.mocked(api.connectors).mockResolvedValue(connectors)
    vi.mocked(api.resources).mockResolvedValue([])
  })

  it('loads services, connectors and resources on mount', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('Open WebUI')
    // Fetches beyond the API default page size so no catalog service is silently hidden.
    expect(api.services).toHaveBeenCalledWith({ limit: '100' })
    expect(api.connectors).toHaveBeenCalled()
    expect(api.resources).toHaveBeenCalled()
  })

  it('warns when connectors and resources cannot be loaded', async () => {
    vi.mocked(api.connectors).mockRejectedValue(new Error('boom'))
    let notifySpy: MockInstance<typeof Notify.create> | undefined
    await mountPage(() => {
      notifySpy = vi.spyOn(Notify, 'create')
    })
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'No se pudieron cargar los conectores y recursos.' }),
    )
  })

  it('switches tabs and only shows the service buttons on the services tab', async () => {
    const { wrapper } = await mountPage()
    wrapper.findComponent({ name: 'QTabs' }).vm.$emit('update:modelValue', 'connectors')
    await flushPromises()
    expect(wrapper.text()).toContain('Plugins de conexión tipados')
    expect(wrapper.text()).toContain('ssh_mole')
    expect(button(wrapper, 'Nuevo servicio')).toBeUndefined()
  })

  it('reloads services and connectors after a successful import from its tab', async () => {
    vi.mocked(api.importCatalog).mockResolvedValue({
      dry_run: false,
      valid: true,
      created: 1,
      updated: 0,
      errors: [],
    })
    const { wrapper } = await mountPage()
    wrapper.findComponent({ name: 'QTabs' }).vm.$emit('update:modelValue', 'importExport')
    await flushPromises()
    vi.mocked(api.services).mockClear()
    vi.mocked(api.connectors).mockClear()

    await wrapper
      .findAll('button')
      .find((candidate) => candidate.text() === 'Importar')
      ?.trigger('click')
    await flushPromises()

    expect(api.importCatalog).toHaveBeenCalledWith(expect.stringContaining('version: 2'), false)
    expect(api.services).toHaveBeenCalled()
    expect(api.connectors).toHaveBeenCalled()
  })

  it('creates a service with runtime, health, logs, metrics and tags through connectors', async () => {
    vi.mocked(api.createService).mockResolvedValue({ ...service, id: 'new-service' })
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nuevo servicio')

    await set(inputs(wrapper, 'ID (slug)')[0], 'new-service')
    await set(inputs(wrapper, 'Nombre')[0], 'Nuevo servicio')
    await set(selects(wrapper, 'Etiquetas')[0], ['ia', 'externo'])
    await set(inputs(wrapper, 'URL del servicio')[0], 'https://svc.home.arpa')
    // Only connectors with the capability each block needs are offered.
    expect(selects(wrapper, 'Conector de estado')[0]?.props('options')).toEqual([
      { label: 'portainer (portainer)', value: 'portainer' },
    ])
    await set(selects(wrapper, 'Conector de estado')[0], 'portainer')
    await set(inputs(wrapper, 'Environment ID de Portainer')[0], '7')
    await set(inputs(wrapper, 'Nombre del stack')[0], 'svc')
    await click(wrapper, 'Añadir contenedor')
    await set(inputs(wrapper, 'Nombre del contenedor')[0], 'app')
    await set(toggles(wrapper, 'Crítico')[0], true)
    // "Conector" selects in DOM order: health, then logs (no dashboard/metric rows yet).
    await set(selects(wrapper, 'Conector')[0], 'http')
    await set(inputs(wrapper, 'URL de comprobación')[0], 'https://svc.home.arpa/health')
    await set(selects(wrapper, 'Conector')[1], 'loki')
    await set(inputs(wrapper, 'Consulta LogQL')[0], '{compose_service="new-service"}')
    await click(wrapper, 'Añadir métrica')
    await set(inputs(wrapper, 'Etiqueta')[0], 'CPU')
    await set(inputs(wrapper, 'Consulta')[0], 'up')

    await saveService(wrapper)

    expect(api.createService).toHaveBeenCalledWith({
      id: 'new-service',
      name: 'Nuevo servicio',
      group_name: 'Plataforma',
      environment: 'homelab',
      description: null,
      icon: null,
      tags: ['ia', 'externo'],
      service_url: 'https://svc.home.arpa',
      documentation_url: null,
      maintenance: false,
      runtime: {
        connector: 'portainer',
        environment_id: '7',
        stack_name: 'svc',
        aggregation: 'all_required',
        containers: [{ name: 'app', required: true, critical: true }],
      },
      observability: {
        health: {
          connector: 'http',
          url: 'https://svc.home.arpa/health',
          method: 'GET',
          expected_status: 200,
          timeout_seconds: 5,
        },
        dashboards: [],
        logs: { connector: 'loki', query: '{compose_service="new-service"}' },
        metrics: [{ label: 'CPU', connector: 'prometheus', query: 'up' }],
      },
    })
  })

  it('adds a Grafana dashboard with variables, defaulting to the dashboards connector', async () => {
    vi.mocked(api.createService).mockResolvedValue({ ...service, id: 'new-service' })
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nuevo servicio')
    await set(inputs(wrapper, 'ID (slug)')[0], 'new-service')
    await set(inputs(wrapper, 'Nombre')[0], 'Nuevo servicio')
    await click(wrapper, 'Añadir dashboard')
    await set(inputs(wrapper, 'UID del dashboard')[0], 'homelab-generico')
    await set(inputs(wrapper, 'Slug')[0], 'servicio-generico')
    await set(inputs(wrapper, 'Variables')[0], 'var-service=new-service, kiosk=tv')

    await saveService(wrapper)

    expect(api.createService).toHaveBeenCalledWith(
      expect.objectContaining({
        observability: expect.objectContaining({
          dashboards: [
            {
              label: 'grafana',
              connector: 'grafana',
              uid: 'homelab-generico',
              slug: 'servicio-generico',
              url: null,
              variables: { 'var-service': 'new-service', kiosk: 'tv' },
            },
          ],
        }),
      }),
    )
  })

  it('edits a full service, removing its dashboard, and sends expected_version', async () => {
    vi.mocked(api.services).mockResolvedValue({ items: [richService], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.updateService).mockResolvedValue(richService)
    const { wrapper } = await mountPage()

    await wrapper.get(`[aria-label="Editar ${richService.name}"]`).trigger('click')
    await flushPromises()
    expect(inputs(wrapper, 'UID del dashboard')[0]?.props('modelValue')).toBe('dash-1')
    expect(inputs(wrapper, 'Variables')[0]?.props('modelValue')).toBe('var-service=open-webui')
    expect(inputs(wrapper, 'URL de comprobación')[0]?.props('modelValue')).toBe(
      'https://open-webui.home.arpa/health',
    )

    await wrapper.get('[aria-label="Eliminar dashboard"]').trigger('click')
    await flushPromises()
    await saveService(wrapper)

    expect(api.updateService).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({
        expected_version: 2,
        tags: ['ia'],
        runtime: richService.runtime,
        observability: { ...richService.observability, dashboards: [] },
      }),
    )
    expect(api.updateService).toHaveBeenCalledWith(
      'open-webui',
      expect.not.objectContaining({ id: expect.anything() }),
    )
  })

  it('clears the runtime block when the status connector is removed', async () => {
    vi.mocked(api.services).mockResolvedValue({ items: [richService], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.updateService).mockResolvedValue(richService)
    const { wrapper } = await mountPage()
    await wrapper.get(`[aria-label="Editar ${richService.name}"]`).trigger('click')
    await flushPromises()

    await set(selects(wrapper, 'Conector de estado')[0], null)
    expect(inputs(wrapper, 'Environment ID de Portainer')).toHaveLength(0)
    await saveService(wrapper)

    expect(api.updateService).toHaveBeenCalledWith('open-webui', expect.objectContaining({ runtime: null }))
  })

  it('round-trips a Docker Swarm service (services selector) without collapsing it into containers', async () => {
    vi.mocked(api.services).mockResolvedValue({ items: [swarmService], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.updateService).mockResolvedValue(swarmService)
    const { wrapper } = await mountPage()

    await wrapper.get(`[aria-label="Editar ${swarmService.name}"]`).trigger('click')
    await flushPromises()
    expect(selects(wrapper, 'Tipo de selector')[0]?.props('modelValue')).toBe('services')
    expect(inputs(wrapper, 'Nombre del servicio')[0]?.props('modelValue')).toBe('authentik-server')

    await saveService(wrapper)

    expect(api.updateService).toHaveBeenCalledWith(
      'authentik',
      expect.objectContaining({ runtime: swarmService.runtime }),
    )
  })

  it('blocks saving a new service with missing required fields and never calls the API (CR-076)', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.createService).mockClear()
    await click(wrapper, 'Nuevo servicio')
    await saveService(wrapper)
    expect(api.createService).not.toHaveBeenCalled()
  })

  it('surfaces a 409 on a service edit as a clear message (CR-091)', async () => {
    vi.mocked(api.services).mockResolvedValue({
      items: [{ ...service, version: 3 }],
      total: 1,
      offset: 0,
      limit: 50,
    })
    vi.mocked(api.updateService).mockRejectedValue(new ApiError(409, 'Version mismatch'))
    const { wrapper } = await mountPage()
    const notifySpy = vi.spyOn(Notify, 'create')

    await wrapper.get(`[aria-label="Editar ${service.name}"]`).trigger('click')
    await flushPromises()
    await saveService(wrapper)

    expect(api.updateService).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({ expected_version: 3 }),
    )
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('se modificó mientras lo editabas') }),
    )
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

  it('creates a Portainer action bound to a connector, without sending action_type', async () => {
    vi.mocked(api.createAction).mockResolvedValue(action)
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nueva acción')

    // Only action-capable connectors are offered; the first one is preselected.
    const connectorSelect = selects(wrapper, 'Conector de la acción')[0]
    expect(connectorSelect?.props('options')).toEqual([
      { label: 'portainer (portainer)', value: 'portainer' },
      { label: 'ansible (ansible)', value: 'ansible' },
      { label: 'ssh_mole (ssh)', value: 'ssh_mole' },
    ])
    expect(connectorSelect?.props('modelValue')).toBe('portainer')

    await set(inputs(wrapper, 'Clave (slug)')[0], 'restart')
    await set(inputs(wrapper, 'Etiqueta')[0], 'Reiniciar')
    // The service dialog renders its own "Descripción"/"Icono" first.
    await set(inputs(wrapper, 'Descripción')[1], 'Reinicia el contenedor.')
    await set(inputs(wrapper, 'Icono')[1], 'restart_alt')
    await set(selects(wrapper, 'Operación Portainer')[0], 'logs')
    await set(selects(wrapper, 'Riesgo')[0], 'operate')
    await set(toggles(wrapper, 'Requiere confirmación')[0], true)
    await set(toggles(wrapper, 'Desatendida (no navega al detalle)')[0], true)
    await set(toggles(wrapper, 'Habilitada')[0], false)
    await saveAction(wrapper)

    expect(api.createAction).toHaveBeenCalledWith('open-webui', {
      key: 'restart',
      label: 'Reiniciar',
      description: 'Reinicia el contenedor.',
      icon: 'restart_alt',
      connector: 'portainer',
      risk_level: 'operate',
      requires_confirmation: true,
      enabled: false,
      unattended: true,
      config: { operation: 'logs', target: 'selected_containers' },
      allowed_parameters_schema: {},
    })
  })

  it('switches to an Ansible connector: no inventory field, the connector provides it', async () => {
    vi.mocked(api.createAction).mockResolvedValue(action)
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nueva acción')
    await set(selects(wrapper, 'Conector de la acción')[0], 'ansible')

    expect(wrapper.text()).toContain('Playbook')
    expect(wrapper.text()).not.toContain('Operación Portainer')
    expect(selects(wrapper, 'Inventario')).toHaveLength(0)

    await set(inputs(wrapper, 'Clave (slug)')[0], 'backup')
    await set(inputs(wrapper, 'Etiqueta')[0], 'Backup')
    await set(selects(wrapper, 'Playbook')[0], 'playbooks/backup_service.yml')
    await set(inputs(wrapper, 'Limit (host/grupo)')[0], 'node-ai-01')
    await set(inputs(wrapper, 'Timeout de Ansible (segundos)')[0], 600)
    await set(inputs(wrapper, 'Extra var: service')[0], 'open-webui')
    await set(inputs(wrapper, 'Extra var: backup_label')[0], 'nightly')
    // Clearing it back out exercises the "unset" branch of the extra_vars setter.
    await set(inputs(wrapper, 'Extra var: backup_label')[0], '')
    await saveAction(wrapper)

    expect(api.createAction).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({
        connector: 'ansible',
        config: {
          playbook: 'playbooks/backup_service.yml',
          limit: 'node-ai-01',
          extra_vars: { service: 'open-webui' },
          timeout_seconds: 600,
        },
      }),
    )
  })

  it('creates an SSH action from the allow-listed commands with key=value params', async () => {
    vi.mocked(api.createAction).mockResolvedValue(action)
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nueva acción')
    await set(selects(wrapper, 'Conector de la acción')[0], 'ssh_mole')

    const commandSelect = selects(wrapper, 'Comando (allow-list)')[0]
    expect(commandSelect?.props('options')).toContain('disk_usage')
    await set(inputs(wrapper, 'Clave (slug)')[0], 'disk')
    await set(inputs(wrapper, 'Etiqueta')[0], 'Disco')
    await set(commandSelect, 'disk_usage')
    await set(inputs(wrapper, 'Parámetros')[0], 'path=/srv')
    await saveAction(wrapper)

    expect(api.createAction).toHaveBeenCalledWith(
      'open-webui',
      expect.objectContaining({
        connector: 'ssh_mole',
        config: { command_id: 'disk_usage', params: { path: '/srv' } },
      }),
    )
  })

  it('defaults a new Portainer action to selected_services for a Swarm service', async () => {
    vi.mocked(api.services).mockResolvedValue({ items: [swarmService], total: 1, offset: 0, limit: 50 })
    const { wrapper } = await mountPage()
    await click(wrapper, 'Nueva acción')
    expect(selects(wrapper, 'Objetivo')[0]?.props('modelValue')).toBe('selected_services')
  })

  it('edits an action, keeping its key and connector (CR-071)', async () => {
    const swarmAction: ActionDefinition = {
      ...action,
      id: 'a2',
      service_id: 'authentik',
      config: { operation: 'restart', target: 'selected_services' },
    }
    vi.mocked(api.services).mockResolvedValue({ items: [swarmService], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.actions).mockResolvedValue([swarmAction])
    vi.mocked(api.updateAction).mockResolvedValue(swarmAction)
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('restart · portainer (Portainer)')

    await wrapper.get(`[aria-label="Editar acción ${swarmAction.label}"]`).trigger('click')
    await flushPromises()
    expect(selects(wrapper, 'Objetivo')[0]?.props('modelValue')).toBe('selected_services')
    await set(inputs(wrapper, 'Etiqueta')[0], 'Reiniciar servicio')
    await saveAction(wrapper)

    expect(api.updateAction).toHaveBeenCalledWith(
      'authentik',
      'restart',
      expect.objectContaining({
        key: 'restart',
        label: 'Reiniciar servicio',
        connector: 'portainer',
        config: { operation: 'restart', target: 'selected_services' },
      }),
    )
    expect(api.actions).toHaveBeenCalledWith('authentik')
  })

  it('blocks saving a new action with a missing label and never calls the API (CR-076)', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(api.createAction).mockClear()
    await click(wrapper, 'Nueva acción')
    await set(inputs(wrapper, 'Clave (slug)')[0], 'restart')
    await saveAction(wrapper)
    expect(api.createAction).not.toHaveBeenCalled()
  })

  it('shows an error notification when saving an action fails', async () => {
    vi.mocked(api.createAction).mockRejectedValue(new Error('boom'))
    const { wrapper } = await mountPage()
    const notifySpy = vi.spyOn(Notify, 'create')
    await click(wrapper, 'Nueva acción')
    await set(inputs(wrapper, 'Clave (slug)')[0], 'restart')
    await set(inputs(wrapper, 'Etiqueta')[0], 'Reiniciar')
    await saveAction(wrapper)
    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: 'No se pudo guardar la acción.' }),
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
