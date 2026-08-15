<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ServiceStatus } from '@/api/types'
const props = defineProps<{ status?: ServiceStatus; loading?: boolean }>()
const { t } = useI18n()
const colorsAndIcons: Record<ServiceStatus, [string, string]> = {
  healthy: ['positive', 'check_circle'],
  degraded: ['warning', 'warning'],
  down: ['negative', 'cancel'],
  maintenance: ['info', 'build'],
  unknown: ['grey-7', 'help'],
}
const detail = computed(() => colorsAndIcons[props.status ?? 'unknown'] ?? colorsAndIcons.unknown)
const label = computed(() => t(`enums.serviceStatus.${props.status ?? 'unknown'}`))
</script>
<template>
  <q-badge :color="detail[0]" class="status-badge"
    ><q-spinner v-if="loading" size="14px" /><q-icon v-else :name="detail[1]" size="14px" /><span>{{
      label
    }}</span
    ><span class="sr-only">: {{ t('common.status') }} {{ label }}</span></q-badge
  >
</template>
