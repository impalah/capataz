import { defineStore } from 'pinia'
import { api } from '@/api/capatazApi'
import type { Connector, ConnectorCapability, Resource } from '@/api/types'

/** Connectors and resources: the admin-only building blocks services reference (ADR-008). */
export const useCatalogStore = defineStore('catalog', {
  state: () => ({
    connectors: [] as Connector[],
    resources: [] as Resource[],
  }),
  getters: {
    connectorsWith:
      (state) =>
      (capability: ConnectorCapability): Connector[] =>
        state.connectors.filter((connector) => connector.capabilities.includes(capability)),
  },
  actions: {
    async fetchConnectors(): Promise<void> {
      this.connectors = await api.connectors()
    },
    async fetchResources(): Promise<void> {
      this.resources = await api.resources()
    },
    async fetchAll(): Promise<void> {
      await Promise.all([this.fetchConnectors(), this.fetchResources()])
    },
  },
})
