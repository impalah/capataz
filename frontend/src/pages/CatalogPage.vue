<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Notify } from 'quasar'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ActionFormDialog from '@/components/catalog/ActionFormDialog.vue'
import ConnectorsPanel from '@/components/catalog/ConnectorsPanel.vue'
import ImportExportPanel from '@/components/catalog/ImportExportPanel.vue'
import ResourcesPanel from '@/components/catalog/ResourcesPanel.vue'
import ServiceFormDialog from '@/components/catalog/ServiceFormDialog.vue'
import { api } from '@/api/capatazApi'
import { notifyApiError } from '@/api/notify'
import type { ActionDefinition, Service } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'
import { useServicesStore } from '@/stores/services'
const services = useServicesStore()
const catalog = useCatalogStore()
const { t } = useI18n()
const tab = ref<'services' | 'connectors' | 'resources' | 'importExport'>('services')
const serviceDialog = ref(false)
const editingService = ref<Service>()
const actionDialog = ref(false)
const editingAction = ref<ActionDefinition>()
const actionServiceId = ref<string>()
const confirmServiceDialog = ref(false)
const serviceToDelete = ref<Service>()
const confirmActionDialog = ref(false)
const actionToDelete = ref<ActionDefinition>()

const reloadServices = () => services.fetch({ limit: '100' }, { includeActions: true })
const reloadCatalog = async () => {
  try {
    await catalog.fetchAll()
  } catch (error) {
    notifyApiError(error, t('notify.catalogLoadFailed'))
  }
}
onMounted(() => {
  reloadServices().catch(() => undefined)
  void reloadCatalog()
})
// An import can touch resources, connectors and services at once.
const onImported = async () => {
  await Promise.all([reloadServices(), reloadCatalog()])
}

const newService = () => {
  editingService.value = undefined
  serviceDialog.value = true
}
const editService = (service: Service) => {
  editingService.value = service
  serviceDialog.value = true
}
const requestRemoveService = (service: Service) => {
  serviceToDelete.value = service
  confirmServiceDialog.value = true
}
const removeService = async () => {
  const service = serviceToDelete.value
  if (!service) return
  try {
    await api.deleteService(service.id)
    await reloadServices()
    Notify.create({ type: 'positive', message: t('notify.serviceDeleted') })
  } catch (error) {
    notifyApiError(error, t('notify.serviceDeleteFailed'))
  }
}
const newAction = (serviceId?: string) => {
  editingAction.value = undefined
  actionServiceId.value = serviceId
  actionDialog.value = true
}
const editAction = (action: ActionDefinition) => {
  editingAction.value = action
  actionServiceId.value = action.service_id
  actionDialog.value = true
}
const requestRemoveAction = (action: ActionDefinition) => {
  actionToDelete.value = action
  confirmActionDialog.value = true
}
const removeAction = async () => {
  const action = actionToDelete.value
  if (!action) return
  try {
    await api.deleteAction(action.service_id, action.key)
    await services.fetchActionsFor(action.service_id)
    Notify.create({ type: 'positive', message: t('notify.actionDeleted') })
  } catch (error) {
    notifyApiError(error, t('notify.actionDeleteFailed'))
  }
}
</script>
<template>
  <AppLayout>
    <q-page class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">{{ t('pages.catalog.eyebrow') }}</p>
          <h1>{{ t('pages.catalog.title') }}</h1>
          <p>{{ t('pages.catalog.description') }}</p>
        </div>
        <div v-if="tab === 'services'" class="q-gutter-sm">
          <q-btn
            outline
            color="primary"
            no-caps
            icon="bolt"
            :label="t('pages.catalog.newAction')"
            @click="newAction()"
          />
          <q-btn
            color="primary"
            no-caps
            icon="add"
            :label="t('pages.catalog.newService')"
            @click="newService"
          />
        </div>
      </header>
      <q-tabs
        v-model="tab"
        align="left"
        no-caps
        dense
        active-color="primary"
        indicator-color="primary"
        class="q-mb-md"
      >
        <q-tab name="services" :label="t('pages.catalog.tabs.services')" />
        <q-tab name="connectors" :label="t('pages.catalog.tabs.connectors')" />
        <q-tab name="resources" :label="t('pages.catalog.tabs.resources')" />
        <q-tab name="importExport" :label="t('pages.catalog.tabs.importExport')" />
      </q-tabs>
      <q-tab-panels v-model="tab" class="bg-transparent">
        <q-tab-panel name="services" class="q-pa-none">
          <article class="panel">
            <h2>{{ t('pages.catalog.servicesTitle') }}</h2>
            <q-list separator bordered>
              <q-expansion-item v-for="service in services.items" :key="service.id" group="catalog-services">
                <template #header>
                  <q-item-section>
                    <q-item-label>{{ service.name }}</q-item-label>
                    <q-item-label caption
                      >{{ service.id }} · {{ service.group_name }} · {{ service.environment
                      }}<template v-if="service.runtime">
                        · {{ service.runtime.connector }}</template
                      ></q-item-label
                    >
                    <div v-if="service.tags?.length">
                      <q-chip v-for="tag in service.tags" :key="tag" dense outline size="sm">{{
                        tag
                      }}</q-chip>
                    </div>
                  </q-item-section>
                  <q-item-section side class="row q-gutter-xs">
                    <q-btn
                      flat
                      round
                      icon="edit"
                      :aria-label="t('pages.catalog.editServiceAria', { name: service.name })"
                      @click.stop="editService(service)"
                    />
                    <q-btn
                      flat
                      round
                      color="negative"
                      icon="delete"
                      :aria-label="t('pages.catalog.deleteServiceAria', { name: service.name })"
                      @click.stop="requestRemoveService(service)"
                    />
                  </q-item-section>
                </template>
                <q-list class="action-sublist" separator>
                  <q-item v-for="action in services.actionsByService[service.id] ?? []" :key="action.key">
                    <q-item-section>
                      <q-item-label>{{ action.label }}</q-item-label>
                      <q-item-label caption>
                        {{ action.key }} · {{ action.connector }} ({{
                          t(`enums.actionType.${action.action_type}`)
                        }}) · {{ t(`enums.riskLevel.${action.risk_level}`) }}
                      </q-item-label>
                    </q-item-section>
                    <q-item-section side class="row q-gutter-xs">
                      <q-btn
                        flat
                        round
                        dense
                        icon="edit"
                        :aria-label="t('pages.catalog.editActionAria', { label: action.label })"
                        @click="editAction(action)"
                      />
                      <q-btn
                        flat
                        round
                        dense
                        color="negative"
                        icon="delete"
                        :aria-label="t('pages.catalog.deleteActionAria', { label: action.label })"
                        @click="requestRemoveAction(action)"
                      />
                    </q-item-section>
                  </q-item>
                  <q-item v-if="!services.actionsByService[service.id]?.length">
                    <q-item-section class="text-caption">{{
                      t('pages.catalog.noActionsDeclared')
                    }}</q-item-section>
                  </q-item>
                  <q-item>
                    <q-item-section>
                      <q-btn
                        flat
                        dense
                        no-caps
                        color="primary"
                        icon="bolt"
                        :label="t('pages.catalog.newActionForService')"
                        @click="newAction(service.id)"
                      />
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-expansion-item>
            </q-list>
          </article>
        </q-tab-panel>
        <q-tab-panel name="connectors" class="q-pa-none"><ConnectorsPanel /></q-tab-panel>
        <q-tab-panel name="resources" class="q-pa-none"><ResourcesPanel /></q-tab-panel>
        <q-tab-panel name="importExport" class="q-pa-none"
          ><ImportExportPanel @imported="onImported"
        /></q-tab-panel>
      </q-tab-panels>
      <ServiceFormDialog
        v-model="serviceDialog"
        :service="editingService"
        :connectors="catalog.connectors"
        @saved="reloadServices"
      />
      <ActionFormDialog
        v-model="actionDialog"
        :action="editingAction"
        :service-id="actionServiceId"
        :services="services.items"
        :connectors="catalog.connectors"
        @saved="(serviceId) => services.fetchActionsFor(serviceId)"
      />
      <ConfirmDialog
        v-model="confirmServiceDialog"
        :title="t('pages.catalog.deleteServiceConfirmTitle')"
        :message="t('pages.catalog.deleteServiceConfirmMessage', { name: serviceToDelete?.name ?? '' })"
        @confirm="removeService"
      />
      <ConfirmDialog
        v-model="confirmActionDialog"
        :title="t('pages.catalog.deleteActionConfirmTitle')"
        :message="t('pages.catalog.deleteActionConfirmMessage', { label: actionToDelete?.label ?? '' })"
        @confirm="removeAction"
      />
    </q-page>
  </AppLayout>
</template>
