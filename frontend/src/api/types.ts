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
// Mirrors api/src/capataz_api/domain/specs/connectors.py (docs/adr/008-connectors-and-resources).
export type ConnectorType = 'portainer' | 'prometheus' | 'grafana' | 'loki' | 'http' | 'ansible' | 'ssh'
export type ConnectorCapability = 'status' | 'actions' | 'metrics' | 'health' | 'dashboards' | 'logs'
export type ResourceType = 'secret' | 'ssh_private_key' | 'known_hosts' | 'file'
export type Aggregation = 'all_required' | 'any_healthy'

export interface ContainerStatus {
  name: string
  running: boolean
  healthy?: boolean | null
}
export interface MetricValue {
  label: string
  value: number | null
}
export interface ServiceStatusResult {
  service_id: string
  status: ServiceStatus
  checked_at?: string
  containers: ContainerStatus[]
  external_healthy?: boolean | null
  error?: string
  metrics?: MetricValue[]
}
export interface ContainerSelector {
  name: string
  required?: boolean
  critical?: boolean
}
export interface ServiceSelector {
  name: string
  replicas?: number
  required?: boolean
  critical?: boolean
}
/** Where the service runs: a `status`-capable connector (Portainer) plus exactly one selector kind. */
export interface RuntimeSpec {
  connector: string
  environment_id: string
  stack_name?: string | null
  aggregation?: Aggregation
  containers?: ContainerSelector[] | null
  services?: ServiceSelector[] | null
}
export interface HealthSpec {
  connector: string
  url: string
  method?: 'GET' | 'HEAD'
  expected_status?: number
  timeout_seconds?: number
}
export interface DashboardSpec {
  label?: string
  connector: string
  uid?: string | null
  slug?: string | null
  url?: string | null
  variables?: Record<string, string>
}
export interface LogsSpec {
  connector: string
  query: string
}
export interface MetricSpec {
  label: string
  connector: string
  query: string
}
export interface ObservabilitySpec {
  health?: HealthSpec | null
  dashboards?: DashboardSpec[]
  logs?: LogsSpec | null
  metrics?: MetricSpec[]
}
export interface Service {
  id: string
  name: string
  description?: string | null
  group_name: string
  environment: string
  icon?: string | null
  tags?: string[]
  service_url?: string | null
  documentation_url?: string | null
  runtime?: RuntimeSpec | null
  observability?: ObservabilitySpec
  metadata?: Record<string, unknown>
  maintenance?: boolean
  version?: number
}
export interface ActionDefinition {
  id: string
  service_id: string
  key: string
  label: string
  description?: string | null
  icon?: string | null
  /** Always the type of `connector`; read-only, derived by the API. */
  action_type: ActionType
  connector: string
  risk_level: RiskLevel
  requires_confirmation: boolean
  enabled: boolean
  unattended?: boolean
  config: Record<string, unknown>
  allowed_parameters_schema?: Record<string, unknown>
}
/** Body of POST /services/{id}/actions and PATCH .../{key} (the API's ActionSpec). */
export interface ActionInput {
  key: string
  label: string
  description?: string | null
  icon?: string | null
  connector: string
  risk_level: RiskLevel
  requires_confirmation: boolean
  enabled: boolean
  unattended?: boolean
  config: Record<string, unknown>
  allowed_parameters_schema?: Record<string, unknown>
}
export interface Connector {
  id: string
  type: ConnectorType
  description?: string | null
  config: Record<string, unknown>
  capabilities: ConnectorCapability[]
  version: number
  created_at?: string
  updated_at?: string
}
export interface ConnectorInput {
  id: string
  type: ConnectorType
  description?: string | null
  config: Record<string, unknown>
}
/** Metadata only: the API never returns a resource's content. */
export interface Resource {
  id: string
  type: ResourceType
  description?: string | null
  fingerprint: string
  size: number
  source: Record<string, unknown>
  version: number
  created_at?: string
  updated_at?: string
}
export interface ResourceCreate {
  id: string
  type: ResourceType
  description?: string | null
  content_base64: string
}
export interface ResourceContentUpdate {
  content_base64: string
  description?: string | null
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
export interface CatalogFieldError {
  path: string
  message: string
  line?: number | null
}
export interface CatalogImportResult {
  dry_run: boolean
  valid: boolean
  created: number
  updated: number
  errors: CatalogFieldError[]
  warnings?: CatalogFieldError[]
  /** Per kind (resources/connectors/services/actions): {created, updated}. */
  counts?: Record<string, Record<string, number>>
}
