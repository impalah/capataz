<script setup lang="ts">
import { ref } from 'vue'
import { Notify } from 'quasar'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/capatazApi'
import { notifyApiError } from '@/api/notify'
import type { CatalogImportResult } from '@/api/types'
const emit = defineEmits<{ imported: [] }>()
const { t, te } = useI18n()
const yaml = ref(
  'version: 2\nservices:\n  - id: new-service\n    name: Servicio nuevo\n    group_name: Plataforma\n    environment: homelab\n',
)
const result = ref<CatalogImportResult>()
const exportText = ref('')
const kindLabel = (kind: string) =>
  te(`pages.catalog.kinds.${kind}`) ? t(`pages.catalog.kinds.${kind}`) : kind
const dryRun = async () => {
  try {
    result.value = await api.importCatalog(yaml.value, true)
  } catch (error) {
    notifyApiError(error, t('notify.catalogValidateFailed'))
  }
}
const applyImport = async () => {
  try {
    const outcome = await api.importCatalog(yaml.value, false)
    result.value = outcome
    Notify.create({
      type: outcome.valid ? 'positive' : 'negative',
      message: outcome.valid ? t('notify.catalogImported') : t('notify.catalogHasErrors'),
    })
    if (outcome.valid) emit('imported')
  } catch (error) {
    notifyApiError(error, t('notify.catalogImportRejected'))
  }
}
const exportCatalog = async () => {
  try {
    exportText.value = (await api.exportCatalog()).yaml
  } catch (error) {
    notifyApiError(error, t('errors.generic'))
  }
}
</script>
<template>
  <div class="catalog-grid">
    <article class="panel">
      <h2>{{ t('pages.catalog.importTitle') }}</h2>
      <p class="panel-intro">{{ t('pages.catalog.importIntro') }}</p>
      <q-input
        v-model="yaml"
        outlined
        type="textarea"
        autogrow
        :label="t('pages.catalog.yamlLabel')"
        data-testid="yaml-input"
      />
      <div class="q-mt-md q-gutter-sm">
        <q-btn outline color="primary" no-caps :label="t('pages.catalog.dryRun')" @click="dryRun" />
        <q-btn color="primary" no-caps :label="t('pages.catalog.import')" @click="applyImport" />
      </div>
      <q-banner
        v-if="result"
        class="q-mt-md"
        :class="result.valid ? 'success-banner' : 'error-banner'"
        rounded
      >
        {{
          result.valid
            ? t('pages.catalog.importValid', { created: result.created, updated: result.updated })
            : t('pages.catalog.importHasErrors')
        }}
        <ul v-if="result.valid && result.counts && Object.keys(result.counts).length">
          <li v-for="(count, kind) in result.counts" :key="kind">
            {{
              t('pages.catalog.importCounts', {
                kind: kindLabel(String(kind)),
                created: count.created ?? 0,
                updated: count.updated ?? 0,
              })
            }}
          </li>
        </ul>
        <ul v-if="result.errors.length">
          <li v-for="error in result.errors" :key="`${error.path}-${error.message}`">
            {{ error.path }}{{ error.line ? t('pages.catalog.importErrorLine', { line: error.line }) : '' }}:
            {{ error.message }}
          </li>
        </ul>
      </q-banner>
      <q-banner v-if="result?.warnings?.length" class="q-mt-sm warning-banner" rounded>
        {{ t('pages.catalog.importWarnings') }}
        <ul>
          <li v-for="warning in result.warnings" :key="`${warning.path}-${warning.message}`">
            {{ warning.path
            }}{{ warning.line ? t('pages.catalog.importErrorLine', { line: warning.line }) : '' }}:
            {{ warning.message }}
          </li>
        </ul>
      </q-banner>
    </article>
    <article class="panel">
      <h2>{{ t('pages.catalog.exportTitle') }}</h2>
      <p class="panel-intro">{{ t('pages.catalog.exportIntro') }}</p>
      <q-btn
        outline
        color="primary"
        no-caps
        icon="download"
        :label="t('pages.catalog.generateExport')"
        @click="exportCatalog"
      />
      <q-input
        v-if="exportText"
        v-model="exportText"
        class="q-mt-md"
        outlined
        type="textarea"
        autogrow
        readonly
        :label="t('pages.catalog.exportedYamlLabel')"
      />
    </article>
  </div>
</template>
