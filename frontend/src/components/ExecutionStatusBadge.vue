<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ExecutionStatus } from '@/api/types'
const props = defineProps<{ status: ExecutionStatus }>()
const { t } = useI18n()
const colors: Record<ExecutionStatus, string> = {
  queued: 'grey-7',
  running: 'primary',
  succeeded: 'positive',
  failed: 'negative',
  cancelled: 'grey-7',
  timed_out: 'warning',
  rejected: 'negative',
}
const label = computed(() => t(`enums.executionStatus.${props.status}`))
</script>
<template>
  <q-badge :color="colors[status]" class="status-badge"
    >{{ label }}<span class="sr-only">: {{ t('common.status') }} {{ label }}</span></q-badge
  >
</template>
