<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { SUPPORTED_LOCALES, LOCALE_LABELS, persistLocale, type Locale } from '@/i18n'

const { t, locale } = useI18n()
const currentCode = computed(() => locale.value.split('-')[0]?.toUpperCase() ?? locale.value)

const selectLocale = (value: Locale): void => {
  locale.value = value
  persistLocale(value)
}
</script>
<template>
  <q-btn
    flat
    dense
    icon="language"
    :label="currentCode"
    class="q-ml-sm"
    :aria-label="t('components.languageSelector.ariaLabel')"
    data-testid="language-menu"
    ><q-tooltip>{{ t('components.languageSelector.tooltip') }}</q-tooltip
    ><q-menu
      ><q-list style="min-width: 220px"
        ><q-item
          v-for="code in SUPPORTED_LOCALES"
          :key="code"
          v-close-popup
          clickable
          @click="selectLocale(code)"
          ><q-item-section avatar
            ><q-icon
              :name="locale === code ? 'radio_button_checked' : 'radio_button_unchecked'"
          /></q-item-section
          ><q-item-section>{{ LOCALE_LABELS[code] }}</q-item-section></q-item
        ></q-list
      ></q-menu
    ></q-btn
  >
</template>
