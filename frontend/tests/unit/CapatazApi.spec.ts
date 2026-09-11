import { api } from '@/api/capatazApi'
import { request } from '@/api/client'

vi.mock('@/api/client', () => ({ request: vi.fn() }))

describe('capatazApi (thin request() wrappers)', () => {
  beforeEach(() => {
    vi.mocked(request).mockReset()
    vi.mocked(request).mockResolvedValue(undefined)
  })

  it('builds a query string from defined filters only, omitting undefined ones', async () => {
    await api.services({ group: 'IA', environment: undefined })
    expect(request).toHaveBeenCalledWith('/services?group=IA')
  })

  it('requests with no query string when no filters are set', async () => {
    await api.services()
    expect(request).toHaveBeenCalledWith('/services')
  })

  it('execute posts the params as the JSON body', async () => {
    await api.execute('open-webui', 'restart', { reason: 'x' })
    expect(request).toHaveBeenCalledWith('/services/open-webui/actions/restart/execute', {
      method: 'POST',
      body: JSON.stringify({ reason: 'x' }),
    })
  })

  it('importCatalog sends yaml and dry_run as a JSON body matching the API schema', async () => {
    await api.importCatalog('version: 1', true)
    expect(request).toHaveBeenCalledWith('/catalog/import', {
      method: 'POST',
      body: JSON.stringify({ yaml: 'version: 1', dry_run: true }),
    })
  })

  it('covers the remaining thin wrappers', async () => {
    await api.me()
    expect(request).toHaveBeenCalledWith('/auth/me')

    await api.service('open-webui')
    expect(request).toHaveBeenCalledWith('/services/open-webui')

    await api.refresh('open-webui')
    expect(request).toHaveBeenCalledWith('/services/open-webui/refresh-status', { method: 'POST' })

    await api.links('open-webui')
    expect(request).toHaveBeenCalledWith('/services/open-webui/links')

    await api.actions('open-webui')
    expect(request).toHaveBeenCalledWith('/services/open-webui/actions')

    await api.executions({ page: 2 })
    expect(request).toHaveBeenCalledWith('/executions?page=2')

    await api.execution('e-1')
    expect(request).toHaveBeenCalledWith('/executions/e-1')

    await api.events('e-1')
    expect(request).toHaveBeenCalledWith('/executions/e-1/events')

    await api.cancel('e-1')
    expect(request).toHaveBeenCalledWith('/executions/e-1/cancel', { method: 'POST' })

    await api.audits({ offset: 0, limit: 20 })
    expect(request).toHaveBeenCalledWith('/audit-events?offset=0&limit=20')

    await api.createService({ id: 'x' })
    expect(request).toHaveBeenCalledWith('/services', { method: 'POST', body: JSON.stringify({ id: 'x' }) })

    await api.updateService('open-webui', { name: 'New name' })
    expect(request).toHaveBeenCalledWith('/services/open-webui', {
      method: 'PATCH',
      body: JSON.stringify({ name: 'New name' }),
    })

    await api.deleteService('open-webui')
    expect(request).toHaveBeenCalledWith('/services/open-webui', { method: 'DELETE' })

    const actionInput = {
      key: 'restart',
      label: 'Reiniciar',
      connector: 'portainer',
      risk_level: 'operate' as const,
      requires_confirmation: false,
      enabled: true,
      config: { operation: 'restart', target: 'selected_containers' },
    }
    await api.createAction('open-webui', actionInput)
    expect(request).toHaveBeenCalledWith('/services/open-webui/actions', {
      method: 'POST',
      body: JSON.stringify(actionInput),
    })

    await api.updateAction('open-webui', 'restart', actionInput)
    expect(request).toHaveBeenCalledWith('/services/open-webui/actions/restart', {
      method: 'PATCH',
      body: JSON.stringify(actionInput),
    })

    await api.deleteAction('open-webui', 'restart')
    expect(request).toHaveBeenCalledWith('/services/open-webui/actions/restart', { method: 'DELETE' })

    await api.exportCatalog()
    expect(request).toHaveBeenCalledWith('/catalog/export')
  })

  it('covers the connector and resource wrappers, sending expected_version as a query param', async () => {
    const connector = { id: 'loki', type: 'loki' as const, config: { url: 'https://loki.home.arpa' } }
    await api.connectors()
    expect(request).toHaveBeenCalledWith('/connectors')

    await api.createConnector(connector)
    expect(request).toHaveBeenCalledWith('/connectors', { method: 'POST', body: JSON.stringify(connector) })

    await api.updateConnector('loki', connector, 4)
    expect(request).toHaveBeenCalledWith('/connectors/loki?expected_version=4', {
      method: 'PUT',
      body: JSON.stringify(connector),
    })

    await api.updateConnector('loki', connector)
    expect(request).toHaveBeenCalledWith('/connectors/loki', {
      method: 'PUT',
      body: JSON.stringify(connector),
    })

    await api.deleteConnector('loki')
    expect(request).toHaveBeenCalledWith('/connectors/loki', { method: 'DELETE' })

    await api.resources()
    expect(request).toHaveBeenCalledWith('/resources')

    const resource = { id: 'token', type: 'secret' as const, content_base64: 'eA==' }
    await api.createResource(resource)
    expect(request).toHaveBeenCalledWith('/resources', { method: 'POST', body: JSON.stringify(resource) })

    await api.replaceResourceContent('token', { content_base64: 'eQ==' })
    expect(request).toHaveBeenCalledWith('/resources/token/content', {
      method: 'PUT',
      body: JSON.stringify({ content_base64: 'eQ==' }),
    })

    await api.deleteResource('token')
    expect(request).toHaveBeenCalledWith('/resources/token', { method: 'DELETE' })
  })
})
