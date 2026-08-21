/**
 * Contrato manual alineado con /api/v1/openapi.json. Cuando la API esté disponible,
 * ejecutar `API_BASE_URL=http://localhost:8000 npm run generate:openapi` y revisar
 * el diff de openapi.generated.ts antes de sustituir o mapear estos tipos.
 */
export type ServiceStatus = 'healthy' | 'degraded' | 'down' | 'maintenance' | 'unknown'
export type ActionType = 'portainer' | 'ansible' | 'http' | 'ssh' | 'rsync'
export type RiskLevel = 'read' | 'operate' | 'critical'
export type ExecutionStatus =
  'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out' | 'rejected'
export type ExecutionSource = 'ui' | 'api' | 'yaml' | 'n8n' | 'mcp' | 'cron' | 'alert' | 'system'
export type Role = 'capataz-viewer' | 'capataz-operator' | 'capataz-admin'

export interface ContainerStatus {
  name: string
  running: boolean
  healthy?: boolean | null
}
export interface ServiceStatusResult {
  service_id: string
  status: ServiceStatus
  checked_at?: string
  containers: ContainerStatus[]
  external_healthy?: boolean | null
  error?: string
}
export interface ContainerSelector {
  name: string
  required?: boolean
  critical?: boolean
}
export interface ContainerSelectors {
  aggregation?: 'all_required' | 'any_healthy'
  containers?: ContainerSelector[]
}
export interface HealthConfig {
  type?: 'http' | 'tcp'
  url?: string
  expected_status?: number
  timeout_seconds?: number
}
export interface GrafanaConfig {
  dashboard_uid?: string
  variables?: Record<string, string>
}
export interface LokiConfig {
  query?: string
}
export interface Service {
  id: string
  name: string
  description?: string
  group_name: string
  environment: string
  icon?: string
  service_url?: string
  documentation_url?: string
  portainer_environment_id?: string
  portainer_stack_name?: string
  container_selectors?: ContainerSelectors
  health_config?: HealthConfig
  grafana_config?: GrafanaConfig
  loki_config?: LokiConfig
  metadata?: Record<string, string>
  maintenance?: boolean
  version?: number
}
export interface ActionDefinition {
  id: string
  service_id: string
  key: string
  label: string
  description?: string
  icon?: string
  action_type: ActionType
  risk_level: RiskLevel
  requires_confirmation: boolean
  enabled: boolean
  unattended?: boolean
  config: Record<string, unknown>
  allowed_parameters_schema?: Record<string, unknown>
}
export interface ExecutionEvent {
  id: string
  execution_id: string
  sequence: number
  timestamp: string
  level: 'debug' | 'info' | 'warning' | 'error'
  event_type: string
  message: string
  data?: Record<string, unknown>
}
export interface Execution {
  id: string
  // Nullable: SET NULL once the referenced service/action is deleted (CR-077) — use
  // service_id_snapshot (never null) to display the execution's history regardless.
  service_id: string | null
  service_id_snapshot: string
  action_definition_id: string | null
  action_key?: string
  requested_by_subject: string
  requested_by_email?: string
  requested_by_name?: string
  source: ExecutionSource
  params: Record<string, unknown>
  status: ExecutionStatus
  requested_at: string
  started_at?: string
  finished_at?: string
  correlation_id: string
  result_summary?: string
  error_code?: string
  error_summary?: string
}
export interface AuditEvent {
  id: string
  timestamp: string
  actor: string
  actor_name?: string
  actor_email?: string
  action: string
  resource: string
  outcome: 'success' | 'denied' | 'failure'
  request_id?: string
  metadata?: Record<string, unknown>
}
export interface Identity {
  subject: string
  email?: string
  name?: string
  groups: Role[]
  permissions?: string[]
}
export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
export interface CatalogImportResult {
  dry_run: boolean
  valid: boolean
  created: number
  updated: number
  errors: Array<{ path: string; message: string; line?: number }>
}
