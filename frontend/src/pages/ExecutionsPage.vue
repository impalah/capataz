<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ExecutionStatusBadge from '@/components/ExecutionStatusBadge.vue'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useExecutionsStore } from '@/stores/executions'
const executions = useExecutionsStore()
const { t, locale } = useI18n()
const filter = ref('')
const pagination = ref({ page: 1, rowsPerPage: 10, rowsNumber: 0 })
const columns = computed(() => [
  { name: 'id', label: t('pages.executions.columns.id'), field: 'id', align: 'left' as const },
  {
    name: 'service',
    label: t('pages.executions.columns.service'),
    field: 'service_id_snapshot',
    align: 'left' as const,
  },
  {
    name: 'action',
    label: t('pages.executions.columns.action'),
    field: 'action_key',
    align: 'left' as const,
  },
  { name: 'status', label: t('pages.executions.columns.status'), field: 'status', align: 'left' as const },
  { name: 'when', label: t('pages.executions.columns.when'), field: 'requested_at', align: 'left' as const },
])
const rows = computed(() =>
  executions.items.filter((item) =>
    `${item.id} ${item.service_id_snapshot} ${item.action_key ?? ''} ${item.status}`
      .toLowerCase()
      .includes(filter.value.toLowerCase()),
  ),
)
// Real server-side pagination (CR-060): each page change re-fetches the corresponding
// offset/limit window from the backend instead of only ever showing its first page.
const loadPage = async (): Promise<void> => {
  const { page, rowsPerPage } = pagination.value
  await executions.fetch({ offset: (page - 1) * rowsPerPage, limit: rowsPerPage })
  pagination.value.rowsNumber = executions.total
}
const onRequest = async ({
  pagination: requested,
}: {
  pagination: { page: number; rowsPerPage: number }
}): Promise<void> => {
  pagination.value.page = requested.page
  pagination.value.rowsPerPage = requested.rowsPerPage
  await loadPage()
}
const { intervalMs: refreshIntervalMs } = useAutoRefresh(loadPage)
onMounted(() => void loadPage())
</script>
<template>
  <AppLayout
    ><q-page class="page"
      ><header class="page-header">
        <div>
          <p class="eyebrow">{{ t('pages.executions.eyebrow') }}</p>
          <h1>{{ t('pages.executions.title') }}</h1>
          <p>{{ t('pages.executions.description') }}</p>
        </div>
        <div class="row items-center q-gutter-sm">
          <AutoRefreshSelect v-model="refreshIntervalMs" /><q-btn
            flat
            round
            icon="refresh"
            :loading="executions.loading"
            :aria-label="t('pages.executions.refresh')"
            @click="loadPage"
            ><q-tooltip>{{ t('pages.executions.refresh') }}</q-tooltip></q-btn
          >
        </div>
      </header>
      <q-table
        v-model:pagination="pagination"
        :rows="rows"
        :columns="columns"
        row-key="id"
        :rows-number="executions.total"
        :loading="executions.loading"
        flat
        bordered
        :filter="filter"
        :aria-label="t('pages.executions.tableAria')"
        @request="onRequest"
        ><template #top
          ><q-input
            v-model="filter"
            outlined
            dense
            clearable
            :label="t('pages.executions.filterLabel')"
            :hint="t('pages.executions.filterHint')"
            class="table-filter"
            ><template #prepend><q-icon name="search" /></template></q-input></template
        ><template #body-cell-id="props"
          ><q-td :props="props"
            ><RouterLink :to="`/executions/${props.row.id}`">{{ props.value }}</RouterLink></q-td
          ></template
        ><template #body-cell-status="props"
          ><q-td :props="props"><ExecutionStatusBadge :status="props.row.status" /></q-td></template
        ><template #body-cell-when="props"
          ><q-td :props="props">{{ new Date(props.value).toLocaleString(locale) }}</q-td></template
        ><template #no-data
          ><div class="full-width row flex-center q-pa-lg">
            {{ t('pages.executions.noMatch') }}
          </div></template
        ></q-table
      ></q-page
    ></AppLayout
  >
</template>
