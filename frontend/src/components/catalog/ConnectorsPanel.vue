<script setup lang="ts">
import { ref } from 'vue'
import { Notify } from 'quasar'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ConnectorFormDialog from './ConnectorFormDialog.vue'
import { api } from '@/api/capatazApi'
import { notifyApiError } from '@/api/notify'
import type { Connector } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'
const catalog = useCatalogStore()
const { t } = useI18n()
const dialog = ref(false)
const editing = ref<Connector>()
const confirmDelete = ref(false)
const toDelete = ref<Connector>()
/** One line telling where the connector points: its URL, user@host or inventory. */
const target = ({ config }: Connector): string => {
  if (typeof config.url === 'string') return config.url
  if (typeof config.host === 'string')
    return `${typeof config.user === 'string' ? `${config.user}@` : ''}${config.host}`
  return typeof config.inventory === 'string' ? config.inventory : ''
}
const newConnector = () => {
  editing.value = undefined
  dialog.value = true
}
const editConnector = (connector: Connector) => {
  editing.value = connector
  dialog.value = true
}
const requestRemove = (connector: Connector) => {
  toDelete.value = connector
  confirmDelete.value = true
}
const remove = async () => {
  const connector = toDelete.value
  if (!connector) return
  try {
    await api.deleteConnector(connector.id)
    await catalog.fetchConnectors()
    Notify.create({ type: 'positive', message: t('notify.connectorDeleted') })
  } catch (error) {
    // A 409 carries the API's own detail: which services/actions still use the connector.
    notifyApiError(error, t('notify.connectorDeleteFailed'))
  }
}
const reload = async () => {
  try {
    await catalog.fetchConnectors()
  } catch (error) {
    notifyApiError(error, t('notify.catalogLoadFailed'))
  }
}
</script>
<template>
  <article class="panel">
    <div class="row items-start justify-between q-gutter-sm">
      <div>
        <h2>{{ t('pages.catalog.connectors.title') }}</h2>
        <p class="panel-intro">{{ t('pages.catalog.connectors.intro') }}</p>
      </div>
      <q-btn
        color="primary"
        no-caps
        icon="add"
        :label="t('pages.catalog.connectors.newConnector')"
        @click="newConnector"
      />
    </div>
    <q-list v-if="catalog.connectors.length" separator bordered>
      <q-item v-for="connector in catalog.connectors" :key="connector.id">
        <q-item-section>
          <q-item-label>{{ connector.id }}</q-item-label>
          <q-item-label caption>
            {{ t(`enums.connectorType.${connector.type}`)
            }}<template v-if="target(connector)"> · {{ target(connector) }}</template
            ><template v-if="connector.description"> · {{ connector.description }}</template>
          </q-item-label>
          <div class="q-mt-xs">
            <q-chip v-for="capability in connector.capabilities" :key="capability" dense outline size="sm">{{
              t(`enums.capability.${capability}`)
            }}</q-chip>
          </div>
        </q-item-section>
        <q-item-section side class="row q-gutter-xs">
          <q-btn
            flat
            round
            icon="edit"
            :aria-label="t('pages.catalog.connectors.editAria', { id: connector.id })"
            @click="editConnector(connector)"
          />
          <q-btn
            flat
            round
            color="negative"
            icon="delete"
            :aria-label="t('pages.catalog.connectors.deleteAria', { id: connector.id })"
            @click="requestRemove(connector)"
          />
        </q-item-section>
      </q-item>
    </q-list>
    <p v-else class="text-caption">{{ t('pages.catalog.connectors.empty') }}</p>
    <ConnectorFormDialog
      v-model="dialog"
      :connector="editing"
      :resources="catalog.resources"
      @saved="reload"
    />
    <ConfirmDialog
      v-model="confirmDelete"
      :title="t('pages.catalog.connectors.deleteConfirmTitle')"
      :message="t('pages.catalog.connectors.deleteConfirmMessage', { id: toDelete?.id ?? '' })"
      @confirm="remove"
    />
  </article>
</template>
