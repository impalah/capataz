import { createPinia, setActivePinia } from 'pinia'
import { useExecutionsStore } from '@/stores/executions'
import { api } from '@/api/capatazApi'
import type { Execution, ExecutionEvent } from '@/api/types'

vi.mock('@/api/capatazApi', () => ({
  api: {
    executions: vi.fn(),
    execution: vi.fn(),
    events: vi.fn(),
    execute: vi.fn(),
  },
}))

const makeExecution = (id: string, overrides: Partial<Execution> = {}): Execution => ({
  id,
  service_id: 'open-webui',
  service_id_snapshot: 'open-webui',
  action_definition_id: 'a1',
  requested_by_subject: 'tester',
  source: 'ui',
  params: {},
  status: 'queued',
  requested_at: '2026-01-01T10:00:00.000Z',
  correlation_id: `corr-${id}`,
  ...overrides,
})

const events = (id: string): ExecutionEvent[] => [
  {
    id: `evt-${id}`,
    execution_id: id,
    sequence: 1,
    timestamp: '2026-01-01T10:00:00.000Z',
    level: 'info',
    event_type: 'execution_started',
    message: 'started',
  },
]

describe('useExecutionsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('pollDetail swallows errors instead of throwing (CR-056)', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.execution).mockRejectedValue(new Error('network blip'))
    vi.mocked(api.events).mockRejectedValue(new Error('network blip'))
    await expect(store.pollDetail('exec-1')).resolves.toBeUndefined()
  })

  it('discards a stale pollDetail response after navigating to a different execution (CR-057)', async () => {
    const store = useExecutionsStore()
    let resolveFirst: (() => void) | undefined
    vi.mocked(api.execution).mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          if (id === 'exec-1') resolveFirst = () => resolve(makeExecution('exec-1'))
          else resolve(makeExecution(id))
        }),
    )
    vi.mocked(api.events).mockImplementation((id: string) => Promise.resolve(events(id)))

    // fetchDetail('exec-1') starts and is left in flight (never resolved yet).
    const firstFetch = store.fetchDetail('exec-1')
    // Navigate to a different execution before the first one resolves.
    await store.fetchDetail('exec-2')
    expect(store.selected?.id).toBe('exec-2')

    // Now let the stale first fetch resolve.
    resolveFirst?.()
    await firstFetch

    // The stale response for exec-1 must not have overwritten exec-2's state.
    expect(store.selected?.id).toBe('exec-2')
  })

  it('pollDetail does not overwrite state for an execution no longer selected (CR-057)', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.execution).mockImplementation((id: string) => Promise.resolve(makeExecution(id)))
    vi.mocked(api.events).mockImplementation((id: string) => Promise.resolve(events(id)))

    await store.fetchDetail('exec-1')
    expect(store.selected?.id).toBe('exec-1')

    // Simulate navigating away (fetchDetail for a new page) before a stale poll for exec-1 lands.
    await store.fetchDetail('exec-2')
    await store.pollDetail('exec-1')

    expect(store.selected?.id).toBe('exec-2')
  })

  it('discards an older in-flight pollDetail response that resolves after a newer one for the same id (CR-089)', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.events).mockImplementation((id: string) => Promise.resolve(events(id)))
    // A prior fetchDetail is what makes the store "current" for exec-1; only then do the two
    // pollDetail ticks below race each other, matching how ExecutionPage's onMounted+useAutoRefresh
    // actually drive this store.
    vi.mocked(api.execution).mockResolvedValueOnce(makeExecution('exec-1', { status: 'queued' }))
    await store.fetchDetail('exec-1')

    let resolveOlderTick: (() => void) | undefined
    let callCount = 0
    vi.mocked(api.execution).mockImplementation((id: string) => {
      callCount += 1
      const isOlderTick = callCount === 1
      return new Promise((resolve) => {
        if (isOlderTick) {
          // Tick #1: leave in flight so the test controls exactly when it resolves.
          resolveOlderTick = () => resolve(makeExecution(id, { status: 'running' }))
        } else {
          // Tick #2 (newer, same id): resolves immediately with the fresher, terminal status.
          resolve(makeExecution(id, { status: 'succeeded' }))
        }
      })
    })

    const olderTick = store.pollDetail('exec-1') // tick #1, in flight
    const newerTick = store.pollDetail('exec-1') // tick #2, resolves first
    await newerTick
    expect(store.selected?.status).toBe('succeeded')

    // The older tick's response arrives after the newer one already landed.
    resolveOlderTick?.()
    await olderTick

    // Must not have been clobbered back to the stale 'running' status.
    expect(store.selected?.status).toBe('succeeded')
  })

  it('fetch() loads a page of executions', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.executions).mockResolvedValue({
      items: [makeExecution('exec-1'), makeExecution('exec-2')],
      total: 2,
      offset: 0,
      limit: 20,
    })

    await store.fetch({ offset: 0, limit: 20 })

    expect(api.executions).toHaveBeenCalledWith({ offset: 0, limit: 20 })
    expect(store.items).toHaveLength(2)
    expect(store.total).toBe(2)
    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
  })

  it('fetch() surfaces a Spanish error message and resets loading on failure', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.executions).mockRejectedValue(new Error('network'))

    await store.fetch()

    expect(store.error).toBe('No se pudo cargar el historial de ejecuciones.')
    expect(store.loading).toBe(false)
  })

  it('fetchDetail() surfaces a Spanish error message when the API rejects', async () => {
    const store = useExecutionsStore()
    vi.mocked(api.execution).mockRejectedValue(new Error('404'))
    vi.mocked(api.events).mockRejectedValue(new Error('404'))

    await store.fetchDetail('exec-1')

    expect(store.error).toBe('No se pudo cargar la ejecución.')
    expect(store.loading).toBe(false)
  })

  it('execute() creates an execution, selects it and prepends it to the list', async () => {
    const store = useExecutionsStore()
    const execution = makeExecution('exec-new')
    vi.mocked(api.execute).mockResolvedValue(execution)

    const result = await store.execute('open-webui', 'restart', {})

    expect(result).toEqual(execution)
    expect(store.selected).toEqual(execution)
    expect(store.items[0]).toEqual(execution)
    expect(store.total).toBe(1)
  })
})
