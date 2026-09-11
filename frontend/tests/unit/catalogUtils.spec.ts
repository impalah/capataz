import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/capatazApi'
import type { Connector } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'
import { blankToNull, bytesToBase64, connectorOptions, formatPairs, parsePairs } from '@/utils/catalog'

vi.mock('@/api/capatazApi', () => ({ api: { connectors: vi.fn(), resources: vi.fn() } }))

const connectors: Connector[] = [
  { id: 'portainer', type: 'portainer', config: {}, capabilities: ['status', 'actions'], version: 1 },
  { id: 'prometheus', type: 'prometheus', config: {}, capabilities: ['metrics'], version: 1 },
]

describe('catalog utils', () => {
  it('parses and formats key=value pairs', () => {
    expect(parsePairs('a=1, b = 2,, c, =x, url=http://h?q=1')).toEqual({
      a: '1',
      b: '2',
      c: '',
      url: 'http://h?q=1',
    })
    expect(formatPairs({ a: '1', b: 2 })).toBe('a=1, b=2')
    expect(formatPairs(undefined)).toBe('')
    expect(parsePairs(formatPairs({ 'var-service': 'open-webui' }))).toEqual({ 'var-service': 'open-webui' })
  })

  it('turns blank optional text into null', () => {
    expect(blankToNull('  ')).toBeNull()
    expect(blankToNull(undefined)).toBeNull()
    expect(blankToNull(' x ')).toBe('x')
  })

  it('base64-encodes arbitrary bytes, including large inputs', () => {
    expect(bytesToBase64(new TextEncoder().encode('hola'))).toBe(btoa('hola'))
    const large = new Uint8Array(100_000).fill(65)
    expect(atob(bytesToBase64(large))).toHaveLength(100_000)
  })

  it('offers only connectors with the requested capability', () => {
    expect(connectorOptions(connectors, 'metrics')).toEqual([
      { label: 'prometheus (prometheus)', value: 'prometheus' },
    ])
    expect(connectorOptions(connectors, 'logs')).toEqual([])
  })
})

describe('catalog store', () => {
  it('loads connectors and resources and filters connectors by capability', async () => {
    setActivePinia(createPinia())
    vi.mocked(api.connectors).mockResolvedValue(connectors)
    vi.mocked(api.resources).mockResolvedValue([])
    const catalog = useCatalogStore()
    await catalog.fetchAll()
    expect(catalog.connectors).toEqual(connectors)
    expect(catalog.resources).toEqual([])
    expect(catalog.connectorsWith('actions').map((connector) => connector.id)).toEqual(['portainer'])
  })
})
