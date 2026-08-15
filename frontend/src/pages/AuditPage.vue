<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { api } from '@/api/capatazApi'
import type { AuditEvent } from '@/api/types'
const { t, locale } = useI18n()
const items = ref<AuditEvent[]>([])
const loading = ref(false)
const error = ref('')
const pagination = ref({ page: 1, rowsPerPage: 20, rowsNumber: 0 })
const columns = computed(() => [
  { name: 'timestamp', label: t('pages.audit.columns.timestamp'), field: 'timestamp', align: 'left' as const },
  {
    name: 'actor',
    label: t('pages.audit.columns.actor'),
    field: (row: AuditEvent) => row.actor_name || row.actor_email || row.actor,
    align: 'left' as const,
  },
  { name: 'action', label: t('pages.audit.columns.action'), field: 'action', align: 'left' as const },
  { name: 'resource', label: t('pages.audit.columns.resource'), field: 'resource', align: 'left' as const },
  { name: 'outcome', label: t('pages.audit.columns.outcome'), field: 'outcome', align: 'left' as const },
])
const load = async () => {
  loading.value = true
  try {
    const { page, rowsPerPage } = pagination.value
    const result = await api.audits({ offset: (page - 1) * rowsPerPage, limit: rowsPerPage })
    items.value = result.items
    pagination.value.rowsNumber = result.total
    error.value = ''
  } catch {
    error.value = t('pages.audit.loadFailed')
  } finally {
    loading.value = false
  }
}
// Real server-side pagination (CR-060): each page change re-fetches the corresponding
// offset/limit window from the backend instead of only ever showing its first page.
const onRequest = async ({
  pagination: requested,
}: {
  pagination: { page: number; rowsPerPage: number }
}): Promise<void> => {
  pagination.value.page = requested.page
  pagination.value.rowsPerPage = requested.rowsPerPage
  await load()
}
const { intervalMs: refreshIntervalMs } = useAutoRefresh(load)
onMounted(() => void load())
</script>
<template>
  <AppLayout
    ><q-page class="page"
      ><header class="page-header">
        <div>
          <p class="eyebrow">{{ t('pages.audit.eyebrow') }}</p>
          <h1>{{ t('pages.audit.title') }}</h1>
          <p>{{ t('pages.audit.description') }}</p>
        </div>
        <div class="row items-center q-gutter-sm">
          <AutoRefreshSelect v-model="refreshIntervalMs" /><q-btn
            flat
            round
            icon="refresh"
            :loading="loading"
            :aria-label="t('pages.audit.refresh')"
            @click="load"
            ><q-tooltip>{{ t('pages.audit.refresh') }}</q-tooltip></q-btn
          >
        </div>
      </header>
      <q-banner v-if="error" class="error-banner" rounded>{{ error }}</q-banner
      ><q-table
        v-else
        v-model:pagination="pagination"
        :rows="items"
        :columns="columns"
        row-key="id"
        :rows-number="pagination.rowsNumber"
        :loading="loading"
        flat
        bordered
        @request="onRequest"
        ><template #body-cell-timestamp="props"
          ><q-td :props="props">{{ new Date(props.value).toLocaleString(locale) }}</q-td></template
        ><template #body-cell-resource="props"
          ><q-td :props="props"
            ><RouterLink v-if="props.row.action === 'execution.request'" :to="`/executions/${props.value}`">{{
              props.value
            }}</RouterLink
            ><template v-else>{{ props.value }}</template></q-td
          ></template
        ><template #body-cell-outcome="props"
          ><q-td :props="props"
            ><q-badge :color="props.value === 'success' ? 'positive' : 'negative'">{{
              t(`enums.auditOutcome.${props.value}`)
            }}</q-badge></q-td
          ></template
        ></q-table
      ></q-page
    ></AppLayout
  >
</template>
