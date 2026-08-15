import { defineStore } from 'pinia'
import { api } from '@/api/capatazApi'
import * as oidc from '@/api/oidc'
import { runtimeConfig } from '@/api/runtimeConfig'
import type { Identity, Role } from '@/api/types'

const roleOrder: Record<Role, number> = { 'capataz-viewer': 1, 'capataz-operator': 2, 'capataz-admin': 3 }
const devSubjectByRole: Record<Role, string> = {
  'capataz-admin': 'ana.admin',
  'capataz-operator': 'olmo.operator',
  'capataz-viewer': 'vera.viewer',
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    subject: runtimeConfig.devUser,
    email: 'ana@lab.local',
    name: undefined as string | undefined,
    groups: ['capataz-admin'] as Role[],
    initialized: false,
    unauthorized: false,
    isLoggedIn: false,
    devMockEnabled: runtimeConfig.useMsw,
    loadPromise: null as Promise<void> | null,
  }),
  getters: {
    displayName: (state): string => state.name || state.email || state.subject,
    highestRole: (state): Role =>
      state.groups.reduce(
        (best, role) => (roleOrder[role] > roleOrder[best] ? role : best),
        'capataz-viewer' as Role,
      ),
    isAdmin(): boolean {
      return this.highestRole === 'capataz-admin'
    },
    isOperator(): boolean {
      return roleOrder[this.highestRole] >= roleOrder['capataz-operator']
    },
    canExecute(): (risk: 'read' | 'operate' | 'critical') => boolean {
      return (risk) => {
        if (risk === 'critical') return this.isAdmin
        if (risk === 'operate') return this.isOperator
        // 'read' actions are available to every authenticated role, including plain viewers.
        return true
      }
    },
  },
  actions: {
    applyIdentity(identity: Identity): void {
      this.subject = identity.subject
      this.email = identity.email ?? ''
      this.name = identity.name
      this.groups = identity.groups
    },
    /** Idempotent: safe to call from every route guard / layout mount, only bootstraps once per session. */
    async load(): Promise<void> {
      if (this.devMockEnabled) {
        this.initialized = true
        return
      }
      this.loadPromise ??= this.bootstrapSession()
      return this.loadPromise
    },
    async bootstrapSession(): Promise<void> {
      if (oidc.hasSession()) {
        try {
          this.applyIdentity(await api.me())
          this.isLoggedIn = true
          this.unauthorized = false
        } catch {
          oidc.clearSession()
          this.isLoggedIn = false
        }
      }
      this.initialized = true
    },
    async startLogin(redirectPath = '/'): Promise<void> {
      await oidc.beginAuthorizationRedirect(redirectPath)
    },
    async completeLogin(callbackUrl: string): Promise<string> {
      const redirectPath = await oidc.handleRedirectCallback(callbackUrl)
      this.applyIdentity(await api.me())
      this.isLoggedIn = true
      this.initialized = true
      this.unauthorized = false
      return redirectPath
    },
    async logout(): Promise<void> {
      this.isLoggedIn = false
      this.initialized = false
      this.loadPromise = null
      await oidc.logout()
    },
    selectDevRole(role: Role): void {
      this.groups = [role]
      this.subject = devSubjectByRole[role]
      this.email = `${this.subject}@dev.local`
      this.unauthorized = false
    },
    markUnauthorized(): void {
      this.unauthorized = true
      if (!this.devMockEnabled) {
        oidc.clearSession()
        this.isLoggedIn = false
        this.initialized = false
        this.loadPromise = null
      }
    },
  },
})
