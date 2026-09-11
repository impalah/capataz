<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import { notifyApiError } from '@/api/notify'
import type {
  Aggregation,
  Connector,
  ConnectorCapability,
  ObservabilitySpec,
  RuntimeSpec,
  Service,
} from '@/api/types'
import { aggregations, blankToNull, connectorOptions, formatPairs, parsePairs } from '@/utils/catalog'

interface ContainerRow {
  name: string
  required: boolean
  critical: boolean
}
interface ServiceRow extends ContainerRow {
  replicas: number
}
interface DashboardRow {
  label: string
  connector: string | null
  uid: string
  slug: string
  url: string
  variables: string
}
interface MetricRow {
  label: string
  connector: string | null
  query: string
}

const props = defineProps<{ service?: Service; connectors: Connector[] }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()
const { t } = useI18n()
const formRef = ref<QForm>()
const required = (value: unknown) => !!value || t('common.requiredField')
const selectorKinds = ['containers', 'services'] as const
const healthMethods = ['GET', 'HEAD']
const editing = computed(() => !!props.service)
// Each reference only offers connectors with the capability the API will require of it.
const options = (capability: ConnectorCapability) => connectorOptions(props.connectors, capability)
const noneHint = (capability: ConnectorCapability) =>
  options(capability).length ? undefined : t('pages.catalog.noConnectorsForCapability')
const firstConnector = (capability: ConnectorCapability) => options(capability)[0]?.value ?? null

const form = ref({
  id: '',
  name: '',
  group_name: '',
  environment: '',
  description: '',
  icon: '',
  tags: [] as string[],
  service_url: '',
  documentation_url: '',
  maintenance: false,
})
const runtimeConnector = ref<string | null>(null)
const environmentId = ref('')
const stackName = ref('')
const aggregation = ref<Aggregation>('all_required')
const selectorKind = ref<'containers' | 'services'>('containers')
const containerRows = ref<ContainerRow[]>([])
const serviceRows = ref<ServiceRow[]>([])
const healthConnector = ref<string | null>(null)
const healthUrl = ref('')
const healthMethod = ref<'GET' | 'HEAD'>('GET')
const healthExpectedStatus = ref(200)
const healthTimeoutSeconds = ref(5)
const dashboardRows = ref<DashboardRow[]>([])
const logsConnector = ref<string | null>(null)
const logsQuery = ref('')
const metricRows = ref<MetricRow[]>([])

const load = (service?: Service) => {
  form.value = {
    id: service?.id ?? '',
    name: service?.name ?? '',
    group_name: service?.group_name ?? 'Plataforma',
    environment: service?.environment ?? 'homelab',
    description: service?.description ?? '',
    icon: service?.icon ?? '',
    tags: [...(service?.tags ?? [])],
    service_url: service?.service_url ?? '',
    documentation_url: service?.documentation_url ?? '',
    maintenance: service?.maintenance ?? false,
  }
  const runtime = service?.runtime
  runtimeConnector.value = runtime?.connector ?? null
  environmentId.value = runtime?.environment_id ?? ''
  stackName.value = runtime?.stack_name ?? ''
  aggregation.value = runtime?.aggregation ?? 'all_required'
  selectorKind.value = runtime?.services?.length ? 'services' : 'containers'
  containerRows.value = (runtime?.containers ?? []).map((container) => ({
    name: container.name,
    required: container.required ?? true,
    critical: container.critical ?? false,
  }))
  serviceRows.value = (runtime?.services ?? []).map((item) => ({
    name: item.name,
    replicas: item.replicas ?? 1,
    required: item.required ?? true,
    critical: item.critical ?? false,
  }))
  const observability = service?.observability ?? {}
  healthConnector.value = observability.health?.connector ?? null
  healthUrl.value = observability.health?.url ?? ''
  healthMethod.value = observability.health?.method ?? 'GET'
  healthExpectedStatus.value = observability.health?.expected_status ?? 200
  healthTimeoutSeconds.value = observability.health?.timeout_seconds ?? 5
  dashboardRows.value = (observability.dashboards ?? []).map((dashboard) => ({
    label: dashboard.label ?? 'grafana',
    connector: dashboard.connector,
    uid: dashboard.uid ?? '',
    slug: dashboard.slug ?? '',
    url: dashboard.url ?? '',
    variables: formatPairs(dashboard.variables),
  }))
  logsConnector.value = observability.logs?.connector ?? null
  logsQuery.value = observability.logs?.query ?? ''
  metricRows.value = (observability.metrics ?? []).map((metric) => ({ ...metric }))
}
load(props.service)
watch(open, (isOpen) => {
  if (isOpen) load(props.service)
})

const addContainerRow = () => containerRows.value.push({ name: '', required: true, critical: false })
const removeContainerRow = (index: number) => containerRows.value.splice(index, 1)
const addServiceRow = () => serviceRows.value.push({ name: '', replicas: 1, required: true, critical: false })
const removeServiceRow = (index: number) => serviceRows.value.splice(index, 1)
const addDashboardRow = () =>
  dashboardRows.value.push({
    label: dashboardRows.value.length ? '' : 'grafana',
    connector: firstConnector('dashboards'),
    uid: '',
    slug: '',
    url: '',
    variables: '',
  })
const removeDashboardRow = (index: number) => dashboardRows.value.splice(index, 1)
const addMetricRow = () =>
  metricRows.value.push({ label: '', connector: firstConnector('metrics'), query: '' })
const removeMetricRow = (index: number) => metricRows.value.splice(index, 1)
const addTag = (value: string, done: (item?: string, mode?: 'add' | 'add-unique' | 'toggle') => void) =>
  done(value.trim().toLowerCase(), 'add-unique')

const buildRuntime = (): RuntimeSpec | null => {
  if (!runtimeConnector.value) return null
  const runtime: RuntimeSpec = {
    connector: runtimeConnector.value,
    environment_id: environmentId.value.trim(),
    stack_name: blankToNull(stackName.value),
    aggregation: aggregation.value,
  }
  if (selectorKind.value === 'services') runtime.services = serviceRows.value.filter((row) => row.name.trim())
  else runtime.containers = containerRows.value.filter((row) => row.name.trim())
  return runtime
}
const buildObservability = (): ObservabilitySpec => ({
  health:
    healthConnector.value && healthUrl.value.trim()
      ? {
          connector: healthConnector.value,
          url: healthUrl.value.trim(),
          method: healthMethod.value,
          expected_status: healthExpectedStatus.value,
          timeout_seconds: healthTimeoutSeconds.value,
        }
      : null,
  dashboards: dashboardRows.value
    .filter((row) => row.connector && (row.uid.trim() || row.url.trim()))
    .map((row) => ({
      label: row.label.trim() || 'grafana',
      connector: row.connector ?? '',
      uid: blankToNull(row.uid),
      slug: blankToNull(row.slug),
      url: blankToNull(row.url),
      variables: parsePairs(row.variables),
    })),
  logs:
    logsConnector.value && logsQuery.value.trim()
      ? { connector: logsConnector.value, query: logsQuery.value.trim() }
      : null,
  metrics: metricRows.value
    .filter((row) => row.connector && row.label.trim() && row.query.trim())
    .map((row) => ({ label: row.label.trim(), connector: row.connector ?? '', query: row.query.trim() })),
})
const save = async () => {
  if (!(await formRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  const {
    id,
    name,
    group_name,
    environment,
    description,
    icon,
    tags,
    service_url,
    documentation_url,
    maintenance,
  } = form.value
  // Every field is always sent (runtime/observability as whole blocks) so a value the operator
  // cleared is persisted instead of silently keeping the previous one; `metadata` is not edited
  // here and a PATCH leaves it untouched.
  const payload = {
    name: name.trim(),
    group_name: group_name.trim(),
    environment: environment.trim(),
    description: blankToNull(description),
    icon: blankToNull(icon),
    tags,
    service_url: blankToNull(service_url),
    documentation_url: blankToNull(documentation_url),
    maintenance,
    runtime: buildRuntime(),
    observability: buildObservability(),
  }
  try {
    if (props.service) {
      // expected_version turns on the backend's optimistic concurrency check (CR-091).
      await api.updateService(props.service.id, { ...payload, expected_version: props.service.version })
    } else {
      await api.createService({ id: id.trim(), ...payload })
    }
    open.value = false
    Notify.create({
      type: 'positive',
      message: props.service ? t('notify.serviceUpdated') : t('notify.serviceCreated'),
    })
    emit('saved')
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && props.service) {
      Notify.create({ type: 'negative', message: t('notify.serviceVersionConflict') })
    } else {
      notifyApiError(error, t('notify.serviceSaveFailed'))
    }
  }
}
</script>
<template>
  <q-dialog v-model="open">
    <q-card class="form-card form-card-wide">
      <q-card-section>
        <div class="text-h6">
          {{ editing ? t('pages.catalog.editServiceTitle') : t('pages.catalog.newServiceTitle') }}
        </div>
      </q-card-section>
      <q-form ref="formRef">
        <q-card-section class="q-gutter-md scroll-section">
          <q-input
            v-model="form.id"
            outlined
            :label="t('pages.catalog.idLabel')"
            :disable="editing"
            :rules="[required]"
          />
          <q-input v-model="form.name" outlined :label="t('pages.catalog.nameLabel')" :rules="[required]" />
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
          <q-select
            v-model="form.tags"
            outlined
            multiple
            use-chips
            use-input
            hide-dropdown-icon
            input-debounce="0"
            :label="t('pages.catalog.tagsLabel')"
            :hint="t('pages.catalog.tagsHint')"
            @new-value="addTag"
          />
          <q-input v-model="form.service_url" outlined :label="t('pages.catalog.serviceUrlLabel')" />
          <q-input
            v-model="form.documentation_url"
            outlined
            :label="t('pages.catalog.documentationUrlLabel')"
          />
          <q-toggle v-model="form.maintenance" :label="t('pages.catalog.maintenanceLabel')" />

          <q-separator />
          <div class="text-subtitle2">{{ t('pages.catalog.runtimeSectionTitle') }}</div>
          <q-select
            v-model="runtimeConnector"
            :options="options('status')"
            emit-value
            map-options
            clearable
            outlined
            :label="t('pages.catalog.runtimeConnectorLabel')"
            :hint="noneHint('status') ?? t('pages.catalog.runtimeConnectorHint')"
          />
          <template v-if="runtimeConnector">
            <q-input
              v-model="environmentId"
              outlined
              :label="t('pages.catalog.portainerEnvironmentIdLabel')"
              :rules="[required]"
            />
            <q-input v-model="stackName" outlined :label="t('pages.catalog.portainerStackNameLabel')" />
            <q-select
              v-model="aggregation"
              :options="aggregations"
              outlined
              :label="t('pages.catalog.portainerAggregationLabel')"
            />
            <q-select
              v-model="selectorKind"
              :options="selectorKinds"
              :option-label="(value) => t(`enums.selectorKind.${value}`)"
              outlined
              :label="t('pages.catalog.selectorKindLabel')"
            />
            <template v-if="selectorKind === 'containers'">
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
            </template>
            <template v-else>
              <div class="text-caption">{{ t('pages.catalog.servicesSelectorTitle') }}</div>
              <div v-for="(row, index) in serviceRows" :key="index" class="row q-col-gutter-sm items-center">
                <q-input
                  v-model="row.name"
                  outlined
                  dense
                  class="col"
                  :label="t('pages.catalog.serviceNameLabel')"
                />
                <q-input
                  v-model.number="row.replicas"
                  outlined
                  dense
                  type="number"
                  style="width: 110px"
                  :label="t('pages.catalog.serviceReplicasLabel')"
                />
                <q-toggle v-model="row.required" dense :label="t('pages.catalog.containerRequiredLabel')" />
                <q-toggle v-model="row.critical" dense :label="t('pages.catalog.containerCriticalLabel')" />
                <q-btn
                  flat
                  round
                  dense
                  icon="delete"
                  color="negative"
                  :aria-label="t('pages.catalog.removeServiceAria')"
                  @click="removeServiceRow(index)"
                />
              </div>
              <q-btn
                flat
                dense
                no-caps
                icon="add"
                color="primary"
                :label="t('pages.catalog.addService')"
                @click="addServiceRow"
              />
            </template>
          </template>

          <q-separator />
          <div class="text-subtitle2">{{ t('pages.catalog.healthSectionTitle') }}</div>
          <q-select
            v-model="healthConnector"
            :options="options('health')"
            emit-value
            map-options
            clearable
            outlined
            :label="t('pages.catalog.connectorLabel')"
            :hint="noneHint('health')"
          />
          <template v-if="healthConnector">
            <q-input
              v-model="healthUrl"
              outlined
              :label="t('pages.catalog.healthUrlLabel')"
              :rules="[required]"
            />
            <q-select
              v-model="healthMethod"
              :options="healthMethods"
              outlined
              :label="t('pages.catalog.healthMethodLabel')"
            />
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
          </template>

          <q-separator />
          <div class="text-subtitle2">{{ t('pages.catalog.dashboardsSectionTitle') }}</div>
          <div v-for="(row, index) in dashboardRows" :key="index" class="dashboard-row q-gutter-sm">
            <div class="row q-col-gutter-sm items-center">
              <q-input
                v-model="row.label"
                outlined
                dense
                class="col"
                :label="t('pages.catalog.dashboardLabelLabel')"
              />
              <q-select
                v-model="row.connector"
                :options="options('dashboards')"
                emit-value
                map-options
                outlined
                dense
                class="col"
                :label="t('pages.catalog.connectorLabel')"
              />
              <q-btn
                flat
                round
                dense
                icon="delete"
                color="negative"
                :aria-label="t('pages.catalog.removeDashboardAria')"
                @click="removeDashboardRow(index)"
              />
            </div>
            <div class="row q-col-gutter-sm">
              <q-input
                v-model="row.uid"
                outlined
                dense
                class="col"
                :disable="!!row.url.trim()"
                :label="t('pages.catalog.grafanaDashboardUidLabel')"
              />
              <q-input
                v-model="row.slug"
                outlined
                dense
                class="col"
                :disable="!!row.url.trim()"
                :label="t('pages.catalog.dashboardSlugLabel')"
              />
            </div>
            <q-input
              v-model="row.url"
              outlined
              dense
              :label="t('pages.catalog.dashboardUrlLabel')"
              :hint="t('pages.catalog.dashboardUrlHint')"
            />
            <q-input
              v-model="row.variables"
              outlined
              dense
              :disable="!!row.url.trim()"
              :label="t('pages.catalog.variablesLabel')"
              :hint="t('pages.catalog.variablesHint')"
            />
          </div>
          <q-btn
            flat
            dense
            no-caps
            icon="add"
            color="primary"
            :label="t('pages.catalog.addDashboard')"
            @click="addDashboardRow"
          />

          <q-separator />
          <div class="text-subtitle2">{{ t('pages.catalog.lokiSectionTitle') }}</div>
          <q-select
            v-model="logsConnector"
            :options="options('logs')"
            emit-value
            map-options
            clearable
            outlined
            :label="t('pages.catalog.connectorLabel')"
            :hint="noneHint('logs')"
          />
          <q-input
            v-if="logsConnector"
            v-model="logsQuery"
            outlined
            :label="t('pages.catalog.lokiQueryLabel')"
            :rules="[required]"
          />

          <q-separator />
          <div class="text-subtitle2">{{ t('pages.catalog.metricsSectionTitle') }}</div>
          <div v-for="(row, index) in metricRows" :key="index" class="row q-col-gutter-sm items-center">
            <q-input
              v-model="row.label"
              outlined
              dense
              class="col"
              :label="t('pages.catalog.metricLabelLabel')"
            />
            <q-select
              v-model="row.connector"
              :options="options('metrics')"
              emit-value
              map-options
              outlined
              dense
              class="col"
              :label="t('pages.catalog.connectorLabel')"
            />
            <q-input
              v-model="row.query"
              outlined
              dense
              class="col"
              :label="t('pages.catalog.metricQueryLabel')"
              :hint="t('pages.catalog.metricQueryHint')"
            />
            <q-btn
              flat
              round
              dense
              icon="delete"
              color="negative"
              :aria-label="t('pages.catalog.removeMetricAria')"
              @click="removeMetricRow(index)"
            />
          </div>
          <q-btn
            flat
            dense
            no-caps
            icon="add"
            color="primary"
            :label="t('pages.catalog.addMetric')"
            @click="addMetricRow"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="primary" no-caps :label="t('common.save')" @click="save" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
