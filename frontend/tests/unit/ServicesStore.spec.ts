import { createPinia, setActivePinia } from 'pinia'
import { useServicesStore } from '@/stores/services'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import type { ActionDefinition, Service, ServiceStatusResult } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    status: vi.fn(),
    actions: vi.fn(),
    services: vi.fn(),
    service: vi.fn(),
    links: vi.fn(),
    refresh: vi.fn(),
  },
}))

const service: Service = { id: 'open-webui', name: 'Open WebUI', group_name: 'IA', environment: 'homelab' }
const status: ServiceStatusResult = { service_id: 'open-webui', status: 'healthy', containers: [] }
const restartAction: ActionDefinition = {
  id: 'a1',
  service_id: 'open-webui',
  key: 'restart',
  label: 'Reiniciar',
  action_type: 'portainer',
  risk_level: 'operate',
  requires_confirmation: false,
  enabled: true,
  config: {},
}

describe('useServicesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchStatus stores the status and swallows API errors', async () => {
    const store = useServicesStore()
    vi.mocked(api.status).mockRejectedValue(new ApiError(500, 'boom', 'req-1'))
    await expect(store.fetchStatus('open-webui')).resolves.toBeUndefined()
    expect(store.statuses['open-webui']).toBeUndefined()
  })

  it('fetchActionsFor stores actions and swallows API errors', async () => {
    const store = useServicesStore()
    vi.mocked(api.actions).mockRejectedValue(new Error('boom'))
    await expect(store.fetchActionsFor('open-webui')).resolves.toBeUndefined()
    expect(store.actionsByService['open-webui']).toBeUndefined()
  })

  it("fetch() loads the service list plus each service's status and actions", async () => {
    const store = useServicesStore()
    vi.mocked(api.services).mockResolvedValue({ items: [service], total: 1, offset: 0, limit: 50 })
    vi.mocked(api.status).mockResolvedValue(status)
    vi.mocked(api.actions).mockResolvedValue([restartAction])

    await store.fetch({ group: 'IA' })

    expect(api.services).toHaveBeenCalledWith({ group: 'IA' })
    expect(store.items).toEqual([service])
    expect(store.statuses['open-webui']).toEqual(status)
    expect(store.actionsByService['open-webui']).toEqual([restartAction])
    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
  })

  it('fetch() surfaces a Spanish error message and resets loading when the list call fails', async () => {
    const store = useServicesStore()
    vi.mocked(api.services).mockRejectedValue(new Error('network'))

    await store.fetch()

    expect(store.error).toBe('No se pudieron cargar los servicios. Inténtalo de nuevo.')
    expect(store.loading).toBe(false)
  })

  it('fetchDetail() loads the service, its actions, links and status together', async () => {
    const store = useServicesStore()
    vi.mocked(api.service).mockResolvedValue(service)
    vi.mocked(api.actions).mockResolvedValue([restartAction])
    vi.mocked(api.links).mockResolvedValue({ portainer: 'https://portainer.home.arpa' })
    vi.mocked(api.status).mockResolvedValue(status)

    await store.fetchDetail('open-webui')

    expect(store.selected).toEqual(service)
    expect(store.actions).toEqual([restartAction])
    expect(store.links).toEqual({ portainer: 'https://portainer.home.arpa' })
    expect(store.statuses['open-webui']).toEqual(status)
    expect(store.loading).toBe(false)
  })

  it('fetchDetail() surfaces a Spanish error message when the service cannot be loaded', async () => {
    const store = useServicesStore()
    vi.mocked(api.service).mockRejectedValue(new Error('404'))
    vi.mocked(api.actions).mockResolvedValue([])
    vi.mocked(api.links).mockResolvedValue({})

    await store.fetchDetail('missing')

    expect(store.error).toBe('No se pudo cargar el detalle del servicio.')
    expect(store.loading).toBe(false)
  })

  it('refresh() replaces the cached status for a service', async () => {
    const store = useServicesStore()
    const refreshed: ServiceStatusResult = { ...status, status: 'degraded' }
    vi.mocked(api.refresh).mockResolvedValue(refreshed)

    await store.refresh('open-webui')

    expect(store.statuses['open-webui']).toEqual(refreshed)
  })

  it('clearDetail() resets the selected service, its actions and its links', () => {
    const store = useServicesStore()
    store.selected = service
    store.actions = [restartAction]
    store.links = { portainer: 'x' }

    store.clearDetail()

    expect(store.selected).toBeUndefined()
    expect(store.actions).toEqual([])
    expect(store.links).toEqual({})
  })
})
