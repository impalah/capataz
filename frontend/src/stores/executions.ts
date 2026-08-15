import { defineStore } from 'pinia'
import { api } from '@/api/capatazApi'
import { i18n } from '@/i18n'
import type { Execution, ExecutionEvent } from '@/api/types'

export const useExecutionsStore = defineStore('executions', {
  state: () => ({
    items: [] as Execution[],
    total: 0,
    selected: undefined as Execution | undefined,
    events: [] as ExecutionEvent[],
    loading: false,
    error: '',
    // Tracks which execution id fetchDetail/pollDetail are currently "for", so a late-arriving
    // response after navigating to a different execution can never overwrite the new one's state.
    currentId: undefined as string | undefined,
    // Per-id generation counter (CR-089): currentId alone only guards against switching to a
    // *different* execution mid-flight — it does nothing when two requests for the *same* id (an
    // auto-refresh tick racing a manual refresh, or two ticks in flight at once) resolve out of
    // order. Shared between fetchDetail and pollDetail since both write `selected`/`events` for
    // the same id.
    requestSeq: {} as Record<string, number>,
  }),
  actions: {
    async fetch(filters: Record<string, string | number | undefined> = {}): Promise<void> {
      this.loading = true
      this.error = ''
      try {
        const page = await api.executions(filters)
        this.items = page.items
        this.total = page.total
      } catch {
        this.error = i18n.global.t('pages.executions.loadFailed')
      } finally {
        this.loading = false
      }
    },
    async fetchDetail(id: string): Promise<void> {
      this.currentId = id
      const seq = (this.requestSeq[id] = (this.requestSeq[id] ?? 0) + 1)
      this.loading = true
      this.error = ''
      try {
        const [execution, events] = await Promise.all([api.execution(id), api.events(id)])
        if (this.currentId !== id || this.requestSeq[id] !== seq) return
        this.selected = execution
        this.events = events
      } catch {
        if (this.currentId !== id || this.requestSeq[id] !== seq) return
        this.error = i18n.global.t('pages.execution.loadFailed')
      } finally {
        if (this.currentId === id && this.requestSeq[id] === seq) this.loading = false
      }
    },
    async execute(serviceId: string, actionKey: string, params: Record<string, unknown>): Promise<Execution> {
      const execution = await api.execute(serviceId, actionKey, params)
      this.selected = execution
      this.items.unshift(execution)
      this.total += 1
      return execution
    },
    async pollDetail(id: string): Promise<void> {
      const seq = (this.requestSeq[id] = (this.requestSeq[id] ?? 0) + 1)
      try {
        const [execution, events] = await Promise.all([api.execution(id), api.events(id)])
        if (this.currentId !== id || this.requestSeq[id] !== seq) return
        this.selected = execution
        this.events = events
      } catch {
        // Polling errors are non-fatal (network blip, session invalidated mid-poll); the manual
        // refresh button surfaces a notification instead. Swallowing here avoids an unhandled
        // promise rejection on every tick of the setInterval-driven auto-refresh (CR-056).
      }
    },
  },
})
