import { defineStore } from 'pinia'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import { i18n } from '@/i18n'
import type { ActionDefinition, Service, ServiceStatusResult } from '@/api/types'

export const useServicesStore = defineStore('services', {
  state: () => ({
    items: [] as Service[],
    total: 0,
    selected: undefined as Service | undefined,
    statuses: {} as Record<string, ServiceStatusResult>,
    actionsByService: {} as Record<string, ActionDefinition[]>,
    actions: [] as ActionDefinition[],
    links: {} as Record<string, string>,
    loading: false,
    error: '',
    // Tracks which service id fetchDetail is currently "for", so a late-arriving response after
    // navigating to a different service can never overwrite the new one's state (CR-072).
    currentId: undefined as string | undefined,
    // Per-id, per-resource generation counters (CR-089): fetchDetail and fetchStatus/refresh are
    // guarded independently, because fetchDetail calls fetchStatus itself — sharing one counter
    // between them would make fetchDetail see its own nested call as "a newer request superseded
    // me" and incorrectly skip clearing `loading`.
    detailSeq: {} as Record<string, number>,
    statusSeq: {} as Record<string, number>,
  }),
  actions: {
    async fetchStatus(id: string): Promise<void> {
      const seq = (this.statusSeq[id] = (this.statusSeq[id] ?? 0) + 1)
      try {
        const status = await api.status(id)
        if (this.statusSeq[id] !== seq) return
        this.statuses[id] = status
      } catch (error) {
        // el estado es informativo; su ausencia no debe romper la vista del servicio, pero se
        // registra con su request id para poder correlacionar con los logs del backend (CR-061)
        if (import.meta.env.DEV) {
          const requestId = error instanceof ApiError ? error.requestId : undefined
          console.debug(`No se pudo cargar el estado de ${id} (request_id=${requestId}):`, error)
        }
      }
    },
    async fetchActionsFor(id: string): Promise<void> {
      try {
        this.actionsByService[id] = await api.actions(id)
      } catch (error) {
        // las acciones rápidas son informativas; su ausencia no debe romper la tarjeta
        if (import.meta.env.DEV) {
          const requestId = error instanceof ApiError ? error.requestId : undefined
          console.debug(`No se pudieron cargar las acciones de ${id} (request_id=${requestId}):`, error)
        }
      }
    },
    async fetch(filters: Record<string, string | undefined> = {}): Promise<void> {
      this.loading = true
      this.error = ''
      try {
        const page = await api.services(filters)
        this.items = page.items
        this.total = page.total
        await Promise.all(
          page.items.flatMap((service) => [this.fetchStatus(service.id), this.fetchActionsFor(service.id)]),
        )
      } catch {
        this.error = i18n.global.t('pages.dashboard.loadFailed')
      } finally {
        this.loading = false
      }
    },
    async fetchDetail(id: string): Promise<void> {
      this.currentId = id
      const seq = (this.detailSeq[id] = (this.detailSeq[id] ?? 0) + 1)
      this.loading = true
      this.error = ''
      try {
        const [service, actions, links] = await Promise.all([api.service(id), api.actions(id), api.links(id)])
        if (this.currentId !== id || this.detailSeq[id] !== seq) return
        this.selected = service
        this.actions = actions
        this.links = links
        await this.fetchStatus(id)
      } catch {
        if (this.currentId !== id || this.detailSeq[id] !== seq) return
        this.error = i18n.global.t('pages.serviceDetail.loadFailed')
      } finally {
        if (this.currentId === id && this.detailSeq[id] === seq) this.loading = false
      }
    },
    async refresh(id: string): Promise<void> {
      const seq = (this.statusSeq[id] = (this.statusSeq[id] ?? 0) + 1)
      const status = await api.refresh(id)
      if (this.statusSeq[id] !== seq) return
      this.statuses[id] = status
    },
    clearDetail(): void {
      this.selected = undefined
      this.actions = []
      this.links = {}
    },
  },
})
