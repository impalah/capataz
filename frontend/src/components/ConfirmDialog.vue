<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const props = defineProps<{
  modelValue: boolean
  title: string
  message: string
  confirmLabel?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [] }>()
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
</script>
<template>
  <q-dialog v-model="open" persistent
    ><q-card class="confirm-card"
      ><q-card-section class="row items-center q-gutter-sm"
        ><q-icon name="warning" color="negative" size="28px" />
        <div class="text-h6">{{ title }}</div></q-card-section
      ><q-card-section
        ><p>{{ message }}</p></q-card-section
      ><q-card-actions align="right"
        ><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn
          v-close-popup
          color="negative"
          no-caps
          :label="confirmLabel ?? t('components.confirmDialog.deleteDefault')"
          :aria-label="title"
          data-testid="confirm-delete"
          @click="emit('confirm')" /></q-card-actions></q-card
  ></q-dialog>
</template>
