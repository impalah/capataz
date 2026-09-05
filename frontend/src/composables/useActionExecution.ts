import { ref } from 'vue'
import { Notify } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useExecutionsStore } from '@/stores/executions'
import { notifyApiError } from '@/api/notify'
import type { ActionDefinition } from '@/api/types'

/**
 * Action-execution/confirmation flow used by ServiceDetailPage.vue — extracted to fix
 * duplicated (and previously buggy, see CR-058) confirmation-gating logic (CR-059 in
 * docs/code-review-2026-08.md; it also lived in ServiceCard.vue at the time, since removed).
 */
export function useActionExecution(serviceId: () => string, onUnattendedRefresh?: () => void) {
  const executions = useExecutionsStore()
  const router = useRouter()
  const { t } = useI18n()
  const pending = ref<ActionDefinition>()
  const confirmOpen = ref(false)

  const execute = async (
    action: ActionDefinition,
    opts: { reason?: string; confirmed?: boolean } = {},
  ): Promise<void> => {
    try {
      const body: Record<string, unknown> = {}
      if (opts.reason) body.reason = opts.reason
      // The API requires an explicit `confirmation: true` (on top of a non-empty `reason`) for
      // `critical` actions — it's a separate flag from `reason`, not implied by sending one.
      if (opts.confirmed) body.confirmation = true
      const execution = await executions.execute(serviceId(), action.key, body)
      if (action.unattended) {
        Notify.create({ type: 'positive', message: t('notify.actionSent', { label: action.label }) })
        window.setTimeout(() => onUnattendedRefresh?.(), 1500)
      } else {
        Notify.create({ type: 'positive', message: t('notify.executionCreated') })
        // Lets the execution page's back button return here instead of defaulting to /executions.
        void router.push({ path: `/executions/${execution.id}`, query: { back: `/services/${serviceId()}` } })
      }
    } catch (error) {
      notifyApiError(error, t('notify.executionRejected'))
    }
  }

  const requestAction = (action: ActionDefinition): void => {
    if (action.requires_confirmation || action.risk_level === 'critical') {
      pending.value = action
      confirmOpen.value = true
    } else {
      void execute(action)
    }
  }

  const confirmPending = (reason?: string): void => {
    confirmOpen.value = false
    if (pending.value) void execute(pending.value, { reason, confirmed: true })
  }

  return { pending, confirmOpen, execute, requestAction, confirmPending }
}
