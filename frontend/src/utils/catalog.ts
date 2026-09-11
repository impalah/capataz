import type { Connector, ConnectorCapability, ConnectorType, ResourceType } from '@/api/types'

// The runner's allow-lists have no endpoint exposing them at runtime, so the forms mirror them
// here: runner/src/capataz_runner/actions.py (ALLOWED_PORTAINER_OPERATIONS, ALLOWED_PLAYBOOKS,
// ALLOWED_INVENTORIES) and runner/ssh_commands.yml. The runner re-validates everything anyway —
// adding a playbook or SSH command means touching both places (docs/05-yaml-catalog).
export const portainerOperations = ['start', 'stop', 'restart', 'logs']
export const portainerTargets = ['selected_containers', 'selected_services'] as const
export const ansiblePlaybooks = [
  'playbooks/restart_service.yml',
  'playbooks/backup_service.yml',
  'playbooks/check_connectivity.yml',
]
export const ansibleInventories = ['inventories/homelab.yml', 'inventories/local.yml']
export const sshCommands = ['uptime', 'memory', 'disk_usage', 'docker_ps', 'systemd_status']
export const aggregations = ['all_required', 'any_healthy'] as const
export const connectorTypes: ConnectorType[] = [
  'portainer',
  'prometheus',
  'grafana',
  'loki',
  'http',
  'ansible',
  'ssh',
]
export const resourceTypes: ResourceType[] = ['secret', 'ssh_private_key', 'known_hosts', 'file']
/** Same limit as the API's MAX_RESOURCE_BYTES (domain/specs/resources.py). */
export const MAX_RESOURCE_BYTES = 64 * 1024

/** `a=1, b=2` -> {a: '1', b: '2'}; for small string maps (dashboard variables, SSH params). */
export const parsePairs = (text: string): Record<string, string> =>
  Object.fromEntries(
    text
      .split(',')
      .map((pair) => pair.trim())
      .filter(Boolean)
      .map((pair) => {
        const index = pair.indexOf('=')
        return index < 0 ? [pair, ''] : [pair.slice(0, index).trim(), pair.slice(index + 1).trim()]
      })
      .filter(([key]) => key),
  )
export const formatPairs = (pairs?: unknown): string =>
  pairs && typeof pairs === 'object'
    ? Object.entries(pairs as Record<string, unknown>)
        .map(([key, value]) => `${key}=${String(value)}`)
        .join(', ')
    : ''
/** Optional text fields go to the API as null rather than '' (URL fields reject an empty string). */
export const blankToNull = (value?: string | null): string | null => (value?.trim() ? value.trim() : null)

export const bytesToBase64 = (bytes: Uint8Array): string => {
  let binary = ''
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
  }
  return btoa(binary)
}

export const connectorOptions = (connectors: Connector[], capability: ConnectorCapability) =>
  connectors
    .filter((connector) => connector.capabilities.includes(capability))
    .map((connector) => ({ label: `${connector.id} (${connector.type})`, value: connector.id }))
