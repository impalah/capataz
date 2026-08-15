<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActionDefinition, Service } from '@/api/types'
const { t } = useI18n()
const props = defineProps<{ modelValue: boolean; action?: ActionDefinition; service?: Service }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [reason: string] }>()
const reason = ref('')
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
watch(open, (visible) => {
  if (!visible) reason.value = ''
})
const submit = () => {
  if (reason.value.trim()) emit('confirm', reason.value.trim())
}
</script>
<template>
  <q-dialog v-model="open" persistent
    ><q-card class="confirm-card"
      ><q-card-section class="row items-center q-gutter-sm"
        ><q-icon name="warning" color="negative" size="28px" />
        <div>
          <div class="text-h6">{{ t('components.criticalConfirmDialog.title') }}</div>
          <div class="text-caption">{{ service?.name }} · {{ action?.label }}</div>
        </div></q-card-section
      ><q-card-section
        ><p>
          {{ t('components.criticalConfirmDialog.warning') }}
        </p>
        <q-input
          v-model="reason"
          outlined
          autogrow
          :label="t('components.criticalConfirmDialog.reasonLabel')"
          :rules="[(value) => Boolean(value?.trim()) || t('components.criticalConfirmDialog.reasonRequired')]"
          data-testid="critical-reason" /></q-card-section
      ><q-card-actions align="right"
        ><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn
          color="negative"
          no-caps
          :label="t('components.criticalConfirmDialog.confirm')"
          :disable="!reason.trim()"
          data-testid="critical-confirm"
          @click="submit" /></q-card-actions></q-card
  ></q-dialog>
</template>
