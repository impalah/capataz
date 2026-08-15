import { request } from './client'
import type {
  ActionDefinition,
  AuditEvent,
  CatalogImportResult,
  Execution,
  ExecutionEvent,
  Identity,
  Page,
  Service,
  ServiceStatusResult,
} from './types'

const query = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined) as [string, string][],
  )
  return qs.size ? `?${qs.toString()}` : ''
}
export const api = {
  me: () => request<Identity>('/auth/me'),
  services: (filters: Record<string, string | undefined> = {}) =>
    request<Page<Service>>(`/services${query(filters)}`),
  service: (id: string) => request<Service>(`/services/${id}`),
  status: (id: string) => request<ServiceStatusResult>(`/services/${id}/status`),
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
  createAction: (serviceId: string, action: Partial<ActionDefinition>) =>
    request<ActionDefinition>(`/services/${serviceId}/actions`, {
      method: 'POST',
      body: JSON.stringify(action),
    }),
  updateAction: (serviceId: string, key: string, action: Partial<ActionDefinition>) =>
    request<ActionDefinition>(`/services/${serviceId}/actions/${key}`, {
      method: 'PATCH',
      body: JSON.stringify(action),
    }),
  deleteAction: (serviceId: string, key: string) =>
    request<void>(`/services/${serviceId}/actions/${key}`, { method: 'DELETE' }),
  importCatalog: (yaml: string, dryRun: boolean) =>
    request<CatalogImportResult>('/catalog/import', {
      method: 'POST',
      body: JSON.stringify({ yaml, dry_run: dryRun }),
    }),
  exportCatalog: () => request<{ yaml: string }>('/catalog/export'),
}
