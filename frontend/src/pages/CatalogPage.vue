<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import { notifyApiError } from '@/api/notify'
import type { ActionDefinition, ActionType, CatalogImportResult, Service } from '@/api/types'
import { useServicesStore } from '@/stores/services'
const services = useServicesStore()
const { t } = useI18n()
const yaml = ref(
  'version: 1\nservices:\n  - id: new-service\n    name: Servicio nuevo\n    group_name: Plataforma\n    environment: homelab\n',
)
const importResult = ref<CatalogImportResult>()
const exportText = ref('')
const serviceDialog = ref(false)
const actionDialog = ref(false)
const editing = ref(false)
const editingAction = ref(false)
const serviceFormRef = ref<QForm>()
const actionFormRef = ref<QForm>()
const required = (value: unknown) => !!value || t('common.requiredField')
// Solo se ofrecen los action_type que este formulario sabe rellenar con un config ejecutable de
// verdad (portainer/ansible, ver resolve_action en el runner) — http/ssh/rsync están modelados en
// el dominio pero resolve_action los rechaza siempre en tiempo de ejecución (CR-088), así que
// crearlos desde aquí solo daría acciones permanentemente rotas.
const supportedActionTypes: ActionType[] = ['portainer', 'ansible']
const portainerOperations = ['start', 'stop', 'restart', 'logs']
// Allow-list fijo en runner/src/capataz_runner/actions.py (ALLOWED_PLAYBOOKS/ALLOWED_INVENTORIES):
// no hay endpoint que lo exponga en tiempo de ejecución, así que se refleja aquí igual que
// portainerOperations ya reflejaba ALLOWED_PORTAINER_OPERATIONS. Añadir un playbook nuevo requiere
// tocar ambos sitios (ver docs/05-yaml-catalog.md).
const ansiblePlaybooks = [
  'playbooks/restart_service.yml',
  'playbooks/backup_service.yml',
  'playbooks/check_connectivity.yml',
]
const ansibleInventories = ['inventories/homelab.yml', 'inventories/local.yml']
const healthTypes = ['http', 'tcp']
const aggregations = ['all_required', 'any_healthy']
interface ContainerRow {
  name: string
  required: boolean
  critical: boolean
}
interface VariableRow {
  key: string
  value: string
}
const emptyServiceForm = (): Partial<Service> => ({
  id: '',
  name: '',
  group_name: 'Plataforma',
  environment: 'homelab',
  description: '',
  icon: '',
  service_url: '',
  documentation_url: '',
  maintenance: false,
  portainer_environment_id: '',
  portainer_stack_name: '',
})
const form = ref<Partial<Service>>(emptyServiceForm())
const containerRows = ref<ContainerRow[]>([])
const containerAggregation = ref<'all_required' | 'any_healthy'>('all_required')
const healthType = ref<'http' | 'tcp'>('http')
const healthUrl = ref('')
const healthExpectedStatus = ref(200)
const healthTimeoutSeconds = ref(5)
const grafanaDashboardUid = ref('')
const grafanaVariableRows = ref<VariableRow[]>([])
const lokiQuery = ref('')
// Refleja en los refs "extra" del diálogo lo que ya tenga el servicio (edición) o los limpia
// (alta nueva) — container_selectors/health_config/grafana_config/loki_config son objetos
// anidados que no se pueden bindear directamente a inputs planos como el resto de `form`.
const resetServiceFormExtras = (service?: Service) => {
  const containers = service?.container_selectors?.containers ?? []
  containerRows.value = containers.map((container) => ({
    name: container.name,
    required: container.required ?? true,
    critical: container.critical ?? false,
  }))
  containerAggregation.value = service?.container_selectors?.aggregation ?? 'all_required'
  healthType.value = service?.health_config?.type ?? 'http'
  healthUrl.value = service?.health_config?.url ?? ''
  healthExpectedStatus.value = service?.health_config?.expected_status ?? 200
  healthTimeoutSeconds.value = service?.health_config?.timeout_seconds ?? 5
  grafanaDashboardUid.value = service?.grafana_config?.dashboard_uid ?? ''
  const variables = service?.grafana_config?.variables ?? {}
  grafanaVariableRows.value = Object.entries(variables).map(([key, value]) => ({ key, value }))
  lokiQuery.value = service?.loki_config?.query ?? ''
}
const addContainerRow = () => containerRows.value.push({ name: '', required: true, critical: false })
const removeContainerRow = (index: number) => containerRows.value.splice(index, 1)
const addVariableRow = () => grafanaVariableRows.value.push({ key: '', value: '' })
const removeVariableRow = (index: number) => grafanaVariableRows.value.splice(index, 1)
const defaultActionConfig = (type: ActionType): Record<string, unknown> =>
  type === 'ansible'
    ? { playbook: '', inventory: '', limit: '', extra_vars: {}, timeout_seconds: 300 }
    : { operation: 'restart', target: 'selected_containers' }
const emptyActionForm = (serviceId: string): Partial<ActionDefinition> => ({
  service_id: serviceId,
  key: '',
  label: '',
  description: '',
  icon: '',
  action_type: 'portainer',
  risk_level: 'read',
  requires_confirmation: false,
  enabled: true,
  unattended: false,
  config: defaultActionConfig('portainer'),
})
const actionForm = ref<Partial<ActionDefinition>>(emptyActionForm(''))
const onActionTypeChange = (value: ActionType) => {
  actionForm.value.action_type = value
  actionForm.value.config = defaultActionConfig(value)
}
const portainerOperation = computed({
  get: () => {
    const value = actionForm.value.config?.operation
    return typeof value === 'string' ? value : 'restart'
  },
  set: (value: string) => {
    actionForm.value.config = { ...actionForm.value.config, operation: value }
  },
})
const ansibleField = (key: 'playbook' | 'inventory' | 'limit') =>
  computed({
    get: () => {
      const value = actionForm.value.config?.[key]
      return typeof value === 'string' ? value : ''
    },
    set: (value: string) => {
      actionForm.value.config = { ...actionForm.value.config, [key]: value }
    },
  })
const ansiblePlaybook = ansibleField('playbook')
const ansibleInventory = ansibleField('inventory')
const ansibleLimit = ansibleField('limit')
const ansibleTimeoutSeconds = computed({
  get: () => {
    const value = actionForm.value.config?.timeout_seconds
    return typeof value === 'number' ? value : 300
  },
  set: (value: number) => {
    actionForm.value.config = { ...actionForm.value.config, timeout_seconds: value }
  },
})
const ansibleExtraVar = (key: 'service' | 'backup_label') =>
  computed({
    get: () => {
      const extraVars = actionForm.value.config?.extra_vars
      const value =
        extraVars && typeof extraVars === 'object' ? (extraVars as Record<string, unknown>)[key] : undefined
      return typeof value === 'string' ? value : ''
    },
    set: (value: string) => {
      const extraVars = { ...(actionForm.value.config?.extra_vars as Record<string, string> | undefined) }
      if (value) extraVars[key] = value
      else delete extraVars[key]
      actionForm.value.config = { ...actionForm.value.config, extra_vars: extraVars }
    },
  })
const ansibleExtraVarService = ansibleExtraVar('service')
const ansibleExtraVarBackupLabel = ansibleExtraVar('backup_label')
const confirmServiceDialog = ref(false)
const serviceToDelete = ref<Service>()
const confirmActionDialog = ref(false)
const actionToDelete = ref<ActionDefinition>()
onMounted(() => {
  services.fetch().catch(() => undefined)
})
const dryRun = async () => {
  try {
    importResult.value = await api.importCatalog(yaml.value, true)
  } catch (error) {
    notifyApiError(error, t('notify.catalogValidateFailed'))
  }
}
const applyImport = async () => {
  try {
    const result = await api.importCatalog(yaml.value, false)
    importResult.value = result
    Notify.create({
      type: result.valid ? 'positive' : 'negative',
      message: result.valid ? t('notify.catalogImported') : t('notify.catalogHasErrors'),
    })
    if (result.valid) await services.fetch()
  } catch (error) {
    notifyApiError(error, t('notify.catalogImportRejected'))
  }
}
const exportCatalog = async () => {
  exportText.value = (await api.exportCatalog()).yaml
}
const newService = () => {
  editing.value = false
  form.value = emptyServiceForm()
  resetServiceFormExtras()
  serviceDialog.value = true
}
const editService = (service: Service) => {
  editing.value = true
  form.value = { ...service }
  resetServiceFormExtras(service)
  serviceDialog.value = true
}
const saveService = async () => {
  if (!(await serviceFormRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  // El formulario ahora edita todo el servicio salvo `metadata` (bolsa libre, sin uso funcional
  // ni campo propio hoy — ver docs/05-yaml-catalog.md): siempre se envían explícitamente todos
  // estos campos para que un valor limpiado por el operador (p. ej. borrar la URL de salud) se
  // persista, en vez de quedarse con el valor anterior.
  const {
    name,
    group_name,
    environment,
    description,
    icon,
    service_url,
    documentation_url,
    maintenance,
    portainer_environment_id,
    portainer_stack_name,
    version,
  } = form.value
  const validContainers = containerRows.value.filter((row) => row.name.trim())
  const validVariables = grafanaVariableRows.value.filter((row) => row.key.trim())
  const payload = {
    name,
    group_name,
    environment,
    description,
    icon,
    service_url,
    documentation_url,
    maintenance,
    portainer_environment_id,
    portainer_stack_name,
    container_selectors: validContainers.length
      ? { aggregation: containerAggregation.value, containers: validContainers }
      : {},
    health_config: healthUrl.value.trim()
      ? {
          type: healthType.value,
          url: healthUrl.value,
          expected_status: healthExpectedStatus.value,
          timeout_seconds: healthTimeoutSeconds.value,
        }
      : {},
    grafana_config:
      grafanaDashboardUid.value.trim() || validVariables.length
        ? {
            dashboard_uid: grafanaDashboardUid.value || undefined,
            variables: Object.fromEntries(validVariables.map((row) => [row.key, row.value])),
          }
        : {},
    loki_config: lokiQuery.value.trim() ? { query: lokiQuery.value } : {},
  }
  try {
    if (editing.value && form.value.id) {
      // expected_version activa la protección de concurrencia optimista del backend (CR-091).
      await api.updateService(form.value.id, { ...payload, expected_version: version })
    } else {
      await api.createService({ id: form.value.id, ...payload })
    }
    serviceDialog.value = false
    await services.fetch()
    Notify.create({
      type: 'positive',
      message: editing.value ? t('notify.serviceUpdated') : t('notify.serviceCreated'),
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      Notify.create({
        type: 'negative',
        message: t('notify.serviceVersionConflict'),
      })
    } else {
      notifyApiError(error, t('notify.serviceSaveFailed'))
    }
  }
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
    await services.fetch()
    Notify.create({ type: 'positive', message: t('notify.serviceDeleted') })
  } catch (error) {
    notifyApiError(error, t('notify.serviceDeleteFailed'))
  }
}
const newAction = (serviceId?: string) => {
  editingAction.value = false
  actionForm.value = emptyActionForm(serviceId ?? services.items[0]?.id ?? '')
  actionDialog.value = true
}
const editAction = (action: ActionDefinition) => {
  editingAction.value = true
  actionForm.value = { ...action }
  actionDialog.value = true
}
const saveAction = async () => {
  if (!(await actionFormRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  const serviceId = actionForm.value.service_id
  const key = actionForm.value.key
  if (!serviceId || !key) return
  // Solo los campos que el backend acepta en el cuerpo (ActionInput, extra="forbid" en
  // api/src/capataz_api/adapters/inbound/schemas.py): id/service_id viajan por la URL, nunca por
  // el cuerpo, o el backend responde 422.
  const {
    label,
    description,
    icon,
    action_type,
    risk_level,
    requires_confirmation,
    enabled,
    unattended,
    config,
    allowed_parameters_schema,
  } = actionForm.value
  const payload = {
    key,
    label,
    description,
    icon,
    action_type,
    risk_level,
    requires_confirmation,
    enabled,
    unattended,
    config,
    allowed_parameters_schema,
  }
  try {
    if (editingAction.value) {
      await api.updateAction(serviceId, key, payload)
      Notify.create({ type: 'positive', message: t('notify.actionUpdated') })
    } else {
      await api.createAction(serviceId, payload)
      Notify.create({ type: 'positive', message: t('notify.actionCreated') })
    }
    actionDialog.value = false
    await services.fetchActionsFor(serviceId)
  } catch (error) {
    notifyApiError(error, t('notify.actionSaveFailed'))
  }
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
        <div class="q-gutter-sm">
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
            v-if="importResult"
            class="q-mt-md"
            :class="importResult.valid ? 'success-banner' : 'error-banner'"
            rounded
          >
            {{
              importResult.valid
                ? t('pages.catalog.importValid', {
                    created: importResult.created,
                    updated: importResult.updated,
                  })
                : t('pages.catalog.importHasErrors')
            }}
            <ul v-if="importResult.errors.length">
              <li v-for="error in importResult.errors" :key="error.path">
                {{ error.path
                }}{{ error.line ? t('pages.catalog.importErrorLine', { line: error.line }) : '' }}:
                {{ error.message }}
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
      <article class="panel q-mt-md">
        <h2>{{ t('pages.catalog.servicesTitle') }}</h2>
        <q-list separator bordered>
          <q-expansion-item v-for="service in services.items" :key="service.id" group="catalog-services">
            <template #header>
              <q-item-section>
                <q-item-label>{{ service.name }}</q-item-label>
                <q-item-label caption
                  >{{ service.id }} · {{ service.group_name }} · {{ service.environment }}</q-item-label
                >
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
                    {{ action.key }} · {{ t(`enums.actionType.${action.action_type}`) }} ·
                    {{ t(`enums.riskLevel.${action.risk_level}`) }}
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
      <q-dialog v-model="serviceDialog">
        <q-card class="form-card form-card-wide">
          <q-card-section>
            <div class="text-h6">
              {{ editing ? t('pages.catalog.editServiceTitle') : t('pages.catalog.newServiceTitle') }}
            </div>
          </q-card-section>
          <q-form ref="serviceFormRef">
            <q-card-section class="q-gutter-md scroll-section">
              <q-input
                v-model="form.id"
                outlined
                :label="t('pages.catalog.idLabel')"
                :disable="editing"
                :rules="[required]"
              />
              <q-input
                v-model="form.name"
                outlined
                :label="t('pages.catalog.nameLabel')"
                :rules="[required]"
              />
              <q-input
                v-model="form.group_name"
                outlined
                :label="t('pages.catalog.groupLabel')"
                :rules="[required]"
              />
              <q-input
                v-model="form.environment"
                outlined
                :label="t('pages.catalog.environmentLabel')"
                :rules="[required]"
              />
              <q-input
                v-model="form.description"
                outlined
                type="textarea"
                :label="t('pages.catalog.descriptionLabel')"
              />
              <q-input
                v-model="form.icon"
                outlined
                :label="t('pages.catalog.iconLabel')"
                :hint="t('pages.catalog.iconHint')"
              />
              <q-input v-model="form.service_url" outlined :label="t('pages.catalog.serviceUrlLabel')" />
              <q-input
                v-model="form.documentation_url"
                outlined
                :label="t('pages.catalog.documentationUrlLabel')"
              />
              <q-toggle v-model="form.maintenance" :label="t('pages.catalog.maintenanceLabel')" />
              <q-separator />
              <div class="text-subtitle2">{{ t('pages.catalog.portainerSectionTitle') }}</div>
              <q-input
                v-model="form.portainer_environment_id"
                outlined
                :label="t('pages.catalog.portainerEnvironmentIdLabel')"
              />
              <q-input
                v-model="form.portainer_stack_name"
                outlined
                :label="t('pages.catalog.portainerStackNameLabel')"
              />
              <q-select
                v-model="containerAggregation"
                :options="aggregations"
                outlined
                :label="t('pages.catalog.portainerAggregationLabel')"
              />
              <div class="text-caption">{{ t('pages.catalog.containersTitle') }}</div>
              <div
                v-for="(row, index) in containerRows"
                :key="index"
                class="row q-col-gutter-sm items-center"
              >
                <q-input
                  v-model="row.name"
                  outlined
                  dense
                  class="col"
                  :label="t('pages.catalog.containerNameLabel')"
                />
                <q-toggle v-model="row.required" dense :label="t('pages.catalog.containerRequiredLabel')" />
                <q-toggle v-model="row.critical" dense :label="t('pages.catalog.containerCriticalLabel')" />
                <q-btn
                  flat
                  round
                  dense
                  icon="delete"
                  color="negative"
                  :aria-label="t('pages.catalog.removeContainerAria')"
                  @click="removeContainerRow(index)"
                />
              </div>
              <q-btn
                flat
                dense
                no-caps
                icon="add"
                color="primary"
                :label="t('pages.catalog.addContainer')"
                @click="addContainerRow"
              />
              <q-separator />
              <div class="text-subtitle2">{{ t('pages.catalog.healthSectionTitle') }}</div>
              <q-select
                v-model="healthType"
                :options="healthTypes"
                outlined
                :label="t('pages.catalog.healthTypeLabel')"
              />
              <q-input v-model="healthUrl" outlined :label="t('pages.catalog.healthUrlLabel')" />
              <q-input
                v-model.number="healthExpectedStatus"
                outlined
                type="number"
                :label="t('pages.catalog.healthExpectedStatusLabel')"
              />
              <q-input
                v-model.number="healthTimeoutSeconds"
                outlined
                type="number"
                :label="t('pages.catalog.healthTimeoutSecondsLabel')"
              />
              <q-separator />
              <div class="text-subtitle2">{{ t('pages.catalog.grafanaSectionTitle') }}</div>
              <q-input
                v-model="grafanaDashboardUid"
                outlined
                :label="t('pages.catalog.grafanaDashboardUidLabel')"
              />
              <div class="text-caption">{{ t('pages.catalog.grafanaVariablesTitle') }}</div>
              <div
                v-for="(row, index) in grafanaVariableRows"
                :key="index"
                class="row q-col-gutter-sm items-center"
              >
                <q-input
                  v-model="row.key"
                  outlined
                  dense
                  class="col"
                  :label="t('pages.catalog.variableKeyLabel')"
                />
                <q-input
                  v-model="row.value"
                  outlined
                  dense
                  class="col"
                  :label="t('pages.catalog.variableValueLabel')"
                />
                <q-btn
                  flat
                  round
                  dense
                  icon="delete"
                  color="negative"
                  :aria-label="t('pages.catalog.removeVariableAria')"
                  @click="removeVariableRow(index)"
                />
              </div>
              <q-btn
                flat
                dense
                no-caps
                icon="add"
                color="primary"
                :label="t('pages.catalog.addVariable')"
                @click="addVariableRow"
              />
              <q-separator />
              <div class="text-subtitle2">{{ t('pages.catalog.lokiSectionTitle') }}</div>
              <q-input v-model="lokiQuery" outlined :label="t('pages.catalog.lokiQueryLabel')" />
            </q-card-section>
            <q-card-actions align="right">
              <q-btn v-close-popup flat :label="t('common.cancel')" />
              <q-btn color="primary" no-caps :label="t('common.save')" @click="saveService" />
            </q-card-actions>
          </q-form>
        </q-card>
      </q-dialog>
      <q-dialog v-model="actionDialog">
        <q-card class="form-card form-card-wide">
          <q-card-section>
            <div class="text-h6">
              {{ editingAction ? t('pages.catalog.editActionTitle') : t('pages.catalog.newActionTitle') }}
            </div>
          </q-card-section>
          <q-form ref="actionFormRef">
            <q-card-section class="q-gutter-md scroll-section">
              <q-select
                v-model="actionForm.service_id"
                :options="services.items.map((service) => ({ label: service.name, value: service.id }))"
                emit-value
                map-options
                outlined
                :disable="editingAction"
                :label="t('pages.catalog.serviceLabel')"
                :rules="[required]"
              />
              <q-input
                v-model="actionForm.key"
                outlined
                :label="t('pages.catalog.keyLabel')"
                :disable="editingAction"
                :rules="[required]"
              />
              <q-input
                v-model="actionForm.label"
                outlined
                :label="t('pages.catalog.labelLabel')"
                :rules="[required]"
              />
              <q-input
                v-model="actionForm.description"
                outlined
                type="textarea"
                :label="t('pages.catalog.descriptionLabel')"
              />
              <q-input
                v-model="actionForm.icon"
                outlined
                :label="t('pages.catalog.iconLabel')"
                :hint="t('pages.catalog.iconHint')"
              />
              <q-select
                :model-value="actionForm.action_type"
                :options="
                  supportedActionTypes.map((value) => ({ label: t(`enums.actionType.${value}`), value }))
                "
                emit-value
                map-options
                outlined
                :label="t('pages.catalog.typeLabel')"
                :hint="t('pages.catalog.typeHint')"
                :rules="[required]"
                @update:model-value="onActionTypeChange"
              />
              <template v-if="actionForm.action_type === 'portainer'">
                <q-select
                  v-model="portainerOperation"
                  :options="portainerOperations"
                  outlined
                  :label="t('pages.catalog.operationLabel')"
                  :rules="[required]"
                />
              </template>
              <template v-else-if="actionForm.action_type === 'ansible'">
                <q-select
                  v-model="ansiblePlaybook"
                  :options="ansiblePlaybooks"
                  outlined
                  :label="t('pages.catalog.ansiblePlaybookLabel')"
                  :rules="[required]"
                />
                <q-select
                  v-model="ansibleInventory"
                  :options="ansibleInventories"
                  outlined
                  :label="t('pages.catalog.ansibleInventoryLabel')"
                  :rules="[required]"
                />
                <q-input
                  v-model="ansibleLimit"
                  outlined
                  :label="t('pages.catalog.ansibleLimitLabel')"
                  :hint="t('pages.catalog.ansibleLimitHint')"
                />
                <q-input
                  v-model.number="ansibleTimeoutSeconds"
                  outlined
                  type="number"
                  :label="t('pages.catalog.ansibleTimeoutSecondsLabel')"
                />
                <div class="text-caption">{{ t('pages.catalog.ansibleExtraVarsTitle') }}</div>
                <q-input
                  v-model="ansibleExtraVarService"
                  outlined
                  :label="t('pages.catalog.ansibleExtraVarServiceLabel')"
                />
                <q-input
                  v-model="ansibleExtraVarBackupLabel"
                  outlined
                  :label="t('pages.catalog.ansibleBackupLabelLabel')"
                />
              </template>
              <q-select
                v-model="actionForm.risk_level"
                :options="
                  ['read', 'operate', 'critical'].map((value) => ({
                    label: t(`enums.riskLevel.${value}`),
                    value,
                  }))
                "
                emit-value
                map-options
                outlined
                :label="t('pages.catalog.riskLabel')"
                :rules="[required]"
              />
              <q-toggle
                v-model="actionForm.requires_confirmation"
                :label="t('pages.catalog.requiresConfirmation')"
              />
              <q-toggle v-model="actionForm.unattended" :label="t('pages.catalog.unattendedLabel')" />
              <q-toggle v-model="actionForm.enabled" :label="t('pages.catalog.enabledLabel')" />
            </q-card-section>
            <q-card-actions align="right">
              <q-btn v-close-popup flat :label="t('common.cancel')" />
              <q-btn color="primary" no-caps :label="t('common.save')" @click="saveAction" />
            </q-card-actions>
          </q-form>
        </q-card>
      </q-dialog>
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
