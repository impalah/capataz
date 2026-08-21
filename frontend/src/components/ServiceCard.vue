<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActionDefinition, Service, ServiceStatusResult } from '@/api/types'
import ServiceStatusBadge from './ServiceStatusBadge.vue'
import CriticalConfirmDialog from './CriticalConfirmDialog.vue'
import { useActionExecution } from '@/composables/useActionExecution'
import { useServicesStore } from '@/stores/services'
import { useAuthStore } from '@/stores/auth'
import { notifyApiError } from '@/api/notify'
const props = defineProps<{
  service: Service
  status?: ServiceStatusResult
  actions?: ActionDefinition[]
  canRefresh: boolean
}>()
const { t, locale } = useI18n()
const services = useServicesStore()
const auth = useAuthStore()
const refreshing = ref(false)
const refreshStatus = async (): Promise<void> => {
  if (!props.canRefresh) return
  refreshing.value = true
  try {
    await services.refresh(props.service.id)
  } catch (error) {
    notifyApiError(error, t('notify.statusUpdateFailed'))
  } finally {
    refreshing.value = false
  }
}
const { pending, confirmOpen, requestAction, confirmPending } = useActionExecution(
  () => props.service.id,
  () => {
    services.refresh(props.service.id).catch(() => undefined)
  },
)
const openServiceUrl = (): void => {
  if (!props.service.service_url) return
  window.open(props.service.service_url, '_blank', 'noopener,noreferrer')
}
</script>
<template>
  <article class="service-card">
    <RouterLink
      :to="`/services/${service.id}`"
      class="card-link"
      :aria-label="t('components.serviceCard.viewServiceAria', { name: service.name })"
    />
    <div class="card-top">
      <span
        class="card-icon"
        :class="{ 'card-icon--clickable': service.service_url }"
        :role="service.service_url ? 'button' : undefined"
        :tabindex="service.service_url ? 0 : undefined"
        :aria-label="
          service.service_url
            ? t('components.serviceCard.openServiceAria', { name: service.name })
            : undefined
        "
        @click.stop="openServiceUrl"
        @keydown.enter.space.stop.prevent="openServiceUrl"
        ><q-icon :name="service.icon ?? 'dns'" size="28px" /><q-tooltip v-if="service.service_url">{{
          t('pages.serviceDetail.openService')
        }}</q-tooltip></span
      >
      <div class="card-status">
        <span
          class="card-status-trigger"
          :class="{ 'card-status-trigger--clickable': canRefresh }"
          :role="canRefresh ? 'button' : undefined"
          :tabindex="canRefresh ? 0 : undefined"
          :aria-label="canRefresh ? t('components.serviceCard.updateStatus') : undefined"
          @click.stop="refreshStatus"
          @keydown.enter.space.stop.prevent="refreshStatus"
          ><ServiceStatusBadge :status="status?.status" :loading="refreshing" /><q-icon
            v-if="status?.error"
            name="error"
            color="negative"
            size="16px"
            ><q-tooltip>{{ status.error }}</q-tooltip></q-icon
          ><q-tooltip v-if="canRefresh">{{ t('components.serviceCard.updateStatus') }}</q-tooltip></span
        >
        <span class="card-updated">{{
          status?.checked_at
            ? new Date(status.checked_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
            : '—'
        }}</span>
      </div>
    </div>
    <h2>{{ service.name }}</h2>
    <p>{{ service.description || t('components.serviceCard.noDescription') }}</p>
    <div class="meta">
      <q-chip dense>{{ service.group_name }}</q-chip
      ><q-chip dense outline>{{ service.environment }}</q-chip>
    </div>
    <p class="card-stack">
      {{ t('components.serviceCard.stackLabel', { stack: service.portainer_stack_name ?? '—' }) }}
    </p>
    <div v-if="actions?.length" class="card-actions">
      <q-btn
        v-for="action in actions"
        :key="action.key"
        round
        dense
        flat
        :icon="action.icon ?? 'play_arrow'"
        :aria-label="action.label"
        :disable="!auth.canExecute(action.risk_level) || !action.enabled"
        @click.stop="requestAction(action)"
        ><q-tooltip>{{ action.label }}</q-tooltip></q-btn
      >
    </div>
    <CriticalConfirmDialog
      v-model="confirmOpen"
      :action="pending"
      :service="service"
      @confirm="confirmPending"
    />
  </article>
</template>
