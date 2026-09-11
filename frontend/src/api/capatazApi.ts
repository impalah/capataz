import { request } from './client'
import type {
  ActionDefinition,
  ActionInput,
  AuditEvent,
  CatalogImportResult,
  Connector,
  ConnectorInput,
  Execution,
  ExecutionEvent,
  Identity,
  Page,
  Resource,
  ResourceContentUpdate,
  ResourceCreate,
  Service,
  ServiceStatusResult,
} from './types'

const query = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [key, String(value)]),
  )
  return qs.size ? `?${qs.toString()}` : ''
}
export const api = {
  me: () => request<Identity>('/auth/me'),
  services: (filters: Record<string, string | undefined> = {}) =>
    request<Page<Service>>(`/services${query(filters)}`),
  service: (id: string) => request<Service>(`/services/${id}`),
  refresh: (id: string) => request<ServiceStatusResult>(`/services/${id}/refresh-status`, { method: 'POST' }),
  links: (id: string) => request<Record<string, string>>(`/services/${id}/links`),
  actions: (id: string) => request<ActionDefinition[]>(`/services/${id}/actions`),
  execute: (serviceId: string, actionKey: string, params: Record<string, unknown>) =>
    request<Execution>(`/services/${serviceId}/actions/${actionKey}/execute`, {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  executions: (filters: Record<string, string | number | undefined> = {}) =>
    request<Page<Execution>>(`/executions${query(filters)}`),
  execution: (id: string) => request<Execution>(`/executions/${id}`),
  events: (id: string) => request<ExecutionEvent[]>(`/executions/${id}/events`),
  cancel: (id: string) => request<Execution>(`/executions/${id}/cancel`, { method: 'POST' }),
  audits: (params: { offset?: number; limit?: number } = {}) =>
    request<Page<AuditEvent>>(`/audit-events${query(params)}`),
  createService: (service: Partial<Service>) =>
    request<Service>('/services', { method: 'POST', body: JSON.stringify(service) }),
  updateService: (id: string, service: Partial<Service> & { expected_version?: number }) =>
    request<Service>(`/services/${id}`, { method: 'PATCH', body: JSON.stringify(service) }),
  deleteService: (id: string) => request<void>(`/services/${id}`, { method: 'DELETE' }),
  createAction: (serviceId: string, action: ActionInput) =>
    request<ActionDefinition>(`/services/${serviceId}/actions`, {
      method: 'POST',
      body: JSON.stringify(action),
    }),
  updateAction: (serviceId: string, key: string, action: ActionInput) =>
    request<ActionDefinition>(`/services/${serviceId}/actions/${key}`, {
      method: 'PATCH',
      body: JSON.stringify(action),
    }),
  deleteAction: (serviceId: string, key: string) =>
    request<void>(`/services/${serviceId}/actions/${key}`, { method: 'DELETE' }),
  connectors: () => request<Connector[]>('/connectors'),
  createConnector: (connector: ConnectorInput) =>
    request<Connector>('/connectors', { method: 'POST', body: JSON.stringify(connector) }),
  // expected_version: the same optimistic-concurrency check as a service PATCH (409 on mismatch).
  updateConnector: (id: string, connector: ConnectorInput, expectedVersion?: number) =>
    request<Connector>(`/connectors/${id}${query({ expected_version: expectedVersion })}`, {
      method: 'PUT',
      body: JSON.stringify(connector),
    }),
  deleteConnector: (id: string) => request<void>(`/connectors/${id}`, { method: 'DELETE' }),
  resources: () => request<Resource[]>('/resources'),
  createResource: (resource: ResourceCreate) =>
    request<Resource>('/resources', { method: 'POST', body: JSON.stringify(resource) }),
  replaceResourceContent: (id: string, update: ResourceContentUpdate) =>
    request<Resource>(`/resources/${id}/content`, { method: 'PUT', body: JSON.stringify(update) }),
  deleteResource: (id: string) => request<void>(`/resources/${id}`, { method: 'DELETE' }),
  importCatalog: (yaml: string, dryRun: boolean) =>
    request<CatalogImportResult>('/catalog/import', {
      method: 'POST',
      body: JSON.stringify({ yaml, dry_run: dryRun }),
    }),
  exportCatalog: () => request<{ yaml: string }>('/catalog/export'),
}
