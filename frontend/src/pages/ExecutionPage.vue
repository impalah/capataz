<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ExecutionStatusBadge from '@/components/ExecutionStatusBadge.vue'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useExecutionsStore } from '@/stores/executions'
import { notifyApiError } from '@/api/notify'
import type { ExecutionEvent, ExecutionStatus } from '@/api/types'
const props = defineProps<{ id: string }>()
const executions = useExecutionsStore()
const { t, locale } = useI18n()
const eventLogs = (event: ExecutionEvent): Record<string, string> | undefined => {
  const logs = event.data?.logs
  return logs && typeof logs === 'object' ? (logs as Record<string, string>) : undefined
}
const eventOutput = (event: ExecutionEvent): string | undefined => {
  const output = event.data?.output
  return typeof output === 'string' ? output : undefined
}
const TERMINAL_STATUSES = new Set<ExecutionStatus>([
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'rejected',
])
const refreshing = ref(false)
const poll = async (): Promise<void> => {
  await executions.pollDetail(props.id)
  if (executions.selected && TERMINAL_STATUSES.has(executions.selected.status)) stop()
}
const { intervalMs: refreshIntervalMs, stop, start } = useAutoRefresh(poll)
const refresh = async (): Promise<void> => {
  refreshing.value = true
  try {
    await poll()
  } catch (error) {
    notifyApiError(error, t('notify.executionUpdateFailed'))
  } finally {
    refreshing.value = false
  }
}
const loadExecution = async (id: string) => {
  // A previous execution reaching a terminal state may have stopped the auto-refresh interval;
  // restart it so the newly loaded execution keeps polling if it's still in progress.
  start()
  await executions.fetchDetail(id)
  if (executions.selected && TERMINAL_STATUSES.has(executions.selected.status)) stop()
}
onMounted(() => loadExecution(props.id))
// Vue Router reuses this component instance when navigating between two /executions/:id URLs
// instead of remounting it, so onMounted alone would leave the previous execution on screen (CR-072).
watch(
  () => props.id,
  (id) => void loadExecution(id),
)
</script>
<template>
  <AppLayout
    ><q-page class="page"
      ><q-btn flat icon="arrow_back" :label="t('pages.execution.back')" to="/executions" class="back-link" /><q-banner
        v-if="executions.error"
        class="error-banner"
        rounded
        >{{ executions.error }}</q-banner
      >
      <section v-else-if="executions.selected" class="execution-detail">
        <header class="detail-header">
          <div>
            <p class="eyebrow">
              {{ executions.selected.service_id_snapshot }} · {{ executions.selected.action_key }}
            </p>
            <h1>{{ t('pages.execution.title', { id: executions.selected.id }) }}</h1>
            <p>
              {{ t('pages.execution.requestedByPrefix') }} {{ executions.selected.requested_by_subject
              }}<template
                v-if="executions.selected.requested_by_name || executions.selected.requested_by_email"
                >&nbsp;({{
                  executions.selected.requested_by_name || executions.selected.requested_by_email
                }})</template
              >
              · {{ new Date(executions.selected.requested_at).toLocaleString(locale) }}
            </p>
          </div>
          <div class="status-actions">
            <ExecutionStatusBadge :status="executions.selected.status" /><AutoRefreshSelect
              v-model="refreshIntervalMs"
            /><q-btn
              flat
              round
              icon="refresh"
              :loading="refreshing"
              :aria-label="t('pages.execution.updateStatus')"
              @click="refresh"
              ><q-tooltip>{{ t('pages.execution.updateStatus') }}</q-tooltip></q-btn
            >
          </div>
        </header>
        <div class="execution-grid">
          <article class="panel">
            <h2>{{ t('pages.execution.timeline') }}</h2>
            <q-timeline color="primary"
              ><q-timeline-entry
                v-for="event in executions.events"
                :key="event.id"
                :title="event.event_type"
                :subtitle="new Date(event.timestamp).toLocaleTimeString(locale)"
                :icon="event.level === 'error' ? 'error' : 'check_circle'"
                ><p>{{ event.message }}</p>
                <template v-if="eventLogs(event)"
                  ><div
                    v-for="(text, containerId) in eventLogs(event)"
                    :key="containerId"
                    class="event-log-block"
                  >
                    <p class="event-log-label">{{ containerId }}</p>
                    <pre class="event-log">{{ text }}</pre>
                  </div></template
                >
                <pre v-else-if="eventOutput(event)" class="event-log">{{ eventOutput(event) }}</pre>
              </q-timeline-entry></q-timeline
            >
          </article>
          <article class="panel">
            <h2>{{ t('pages.execution.detail') }}</h2>
            <dl class="detail-list">
              <div>
                <dt>{{ t('pages.execution.status') }}</dt>
                <dd>{{ t(`enums.executionStatus.${executions.selected.status}`) }}</dd>
              </div>
              <div>
                <dt>{{ t('pages.execution.source') }}</dt>
                <dd>{{ t(`enums.executionSource.${executions.selected.source}`) }}</dd>
              </div>
              <div>
                <dt>{{ t('pages.execution.correlation') }}</dt>
                <dd>
                  <code>{{ executions.selected.correlation_id }}</code>
                </dd>
              </div>
              <div v-if="executions.selected.result_summary">
                <dt>{{ t('pages.execution.result') }}</dt>
                <dd>{{ executions.selected.result_summary }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </section>
      <q-inner-loading :showing="executions.loading"><q-spinner size="44px" /></q-inner-loading></q-page
  ></AppLayout>
</template>
