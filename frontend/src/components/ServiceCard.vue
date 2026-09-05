<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Service, ServiceStatusResult } from '@/api/types'
import ServiceStatusBadge from './ServiceStatusBadge.vue'
const props = defineProps<{
  service: Service
  status?: ServiceStatusResult
}>()
const { t, locale } = useI18n()
// Surfaces service health at a glance beyond the small status badge: an unknown status (not
// loaded yet, or the backend genuinely can't tell) mutes the whole card, and "down" flags it red.
const cardStateClass = computed(() => {
  const status = props.status?.status
  if (status === 'down') return 'service-card--down'
  if (!status || status === 'unknown') return 'service-card--unknown'
  return ''
})
</script>
<template>
  <article class="service-card" :class="cardStateClass">
    <RouterLink
      :to="`/services/${service.id}`"
      class="card-link"
      :aria-label="t('components.serviceCard.viewServiceAria', { name: service.name })"
    />
    <div class="card-content">
      <div class="card-row-status">
        <div class="card-status">
          <span class="card-status-trigger"
            ><ServiceStatusBadge :status="status?.status" /><q-icon
              v-if="status?.error"
              class="card-error-icon"
              name="error"
              color="negative"
              size="16px"
              ><q-tooltip>{{ status.error }}</q-tooltip></q-icon
            ></span
          >
          <span class="card-updated">{{
            status?.checked_at
              ? new Date(status.checked_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
              : '—'
          }}</span>
        </div>
      </div>
      <div class="card-row-title">
        <span class="card-icon"><q-icon :name="service.icon ?? 'dns'" size="28px" /></span>
        <h2>{{ service.name }}</h2>
      </div>
    </div>
  </article>
</template>
