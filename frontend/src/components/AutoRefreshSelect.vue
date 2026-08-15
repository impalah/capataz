<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AUTO_REFRESH_OPTIONS } from '@/composables/useAutoRefresh'
defineProps<{ modelValue: number; disable?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
const { t } = useI18n()
</script>
<template>
  <q-select
    :model-value="modelValue"
    :options="AUTO_REFRESH_OPTIONS"
    option-label="label"
    option-value="value"
    emit-value
    map-options
    dense
    outlined
    options-dense
    :disable="disable"
    class="auto-refresh-select"
    :aria-label="t('components.autoRefreshSelect.ariaLabel')"
    @update:model-value="(value) => emit('update:modelValue', value as number)"
    ><q-tooltip>{{ t('components.autoRefreshSelect.tooltip') }}</q-tooltip></q-select
  >
</template>
