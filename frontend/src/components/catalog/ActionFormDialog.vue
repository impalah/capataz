<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/capatazApi'
import { notifyApiError } from '@/api/notify'
import type { ActionDefinition, ActionInput, Connector, ConnectorType, RiskLevel, Service } from '@/api/types'
import {
  ansiblePlaybooks,
  blankToNull,
  connectorOptions,
  formatPairs,
  parsePairs,
  portainerOperations,
  portainerTargets,
  sshCommands,
} from '@/utils/catalog'

const props = defineProps<{
  action?: ActionDefinition
  serviceId?: string
  services: Service[]
  connectors: Connector[]
}>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [serviceId: string] }>()
const { t } = useI18n()
const formRef = ref<QForm>()
const required = (value: unknown) => !!value || t('common.requiredField')
const riskLevels: RiskLevel[] = ['read', 'operate', 'critical']
const emptyForm = () => ({
  service_id: '',
  key: '',
  label: '',
  description: '',
  icon: '',
  connector: null as string | null,
  risk_level: 'read' as RiskLevel,
  requires_confirmation: false,
  enabled: true,
  unattended: false,
})
const form = ref(emptyForm())
const config = ref<Record<string, unknown>>({})
const sshParams = ref('')
const editing = computed(() => !!props.action)
const connectorChoices = computed(() => connectorOptions(props.connectors, 'actions'))
// The connector's type decides which config the action takes (and the runner's executor).
const connectorType = computed<ConnectorType | undefined>(
  () => props.connectors.find((connector) => connector.id === form.value.connector)?.type,
)
const serviceUsesSwarm = computed(
  () => !!props.services.find((service) => service.id === form.value.service_id)?.runtime?.services?.length,
)
const serviceOptions = computed(() =>
  props.services.map((service) => ({ label: service.name, value: service.id })),
)
const riskOptions = computed(() =>
  riskLevels.map((value) => ({ label: t(`enums.riskLevel.${value}`), value })),
)

const defaultConfig = (type?: ConnectorType): Record<string, unknown> => {
  if (type === 'ansible') return { playbook: '', limit: '', extra_vars: {}, timeout_seconds: 300 }
  if (type === 'ssh') return { command_id: '' }
  if (type === 'portainer')
    return {
      operation: 'restart',
      target: serviceUsesSwarm.value ? 'selected_services' : 'selected_containers',
    }
  return {}
}
const load = () => {
  const action = props.action
  if (action) {
    form.value = {
      service_id: action.service_id,
      key: action.key,
      label: action.label,
      description: action.description ?? '',
      icon: action.icon ?? '',
      connector: action.connector,
      risk_level: action.risk_level,
      requires_confirmation: action.requires_confirmation,
      enabled: action.enabled,
      unattended: action.unattended ?? false,
    }
    config.value = { ...action.config }
    sshParams.value = formatPairs(action.config.params)
  } else {
    form.value = {
      ...emptyForm(),
      service_id: props.serviceId ?? props.services[0]?.id ?? '',
      connector: connectorChoices.value[0]?.value ?? null,
    }
    config.value = defaultConfig(connectorType.value)
    sshParams.value = ''
  }
}
load()
watch(open, (isOpen) => {
  if (isOpen) load()
})
const onConnectorChange = (value: string | null) => {
  const previousType = connectorType.value
  form.value.connector = value
  if (connectorType.value !== previousType) config.value = defaultConfig(connectorType.value)
}

const configText = (key: string) =>
  computed({
    get: () => {
      const value = config.value[key]
      return typeof value === 'string' ? value : ''
    },
    set: (value: string) => {
      config.value = { ...config.value, [key]: value }
    },
  })
const portainerOperation = configText('operation')
const portainerTarget = configText('target')
const ansiblePlaybook = configText('playbook')
const ansibleLimit = configText('limit')
const sshCommand = configText('command_id')
const ansibleTimeoutSeconds = computed({
  get: () => (typeof config.value.timeout_seconds === 'number' ? config.value.timeout_seconds : 300),
  set: (value: number) => {
    config.value = { ...config.value, timeout_seconds: value }
  },
})
const ansibleExtraVar = (key: 'service' | 'backup_label') =>
  computed({
    get: () => {
      const extraVars = config.value.extra_vars
      const value =
        extraVars && typeof extraVars === 'object' ? (extraVars as Record<string, unknown>)[key] : undefined
      return typeof value === 'string' ? value : ''
    },
    set: (value: string) => {
      const extraVars = { ...(config.value.extra_vars as Record<string, string> | undefined) }
      if (value) extraVars[key] = value
      else delete extraVars[key]
      config.value = { ...config.value, extra_vars: extraVars }
    },
  })
const ansibleExtraVarService = ansibleExtraVar('service')
const ansibleExtraVarBackupLabel = ansibleExtraVar('backup_label')

/** Only the keys the connector type's action model accepts, so stale ones (e.g. a v1 inventory) go. */
const buildConfig = (): Record<string, unknown> => {
  const values = config.value
  if (connectorType.value === 'ssh') {
    const params = parsePairs(sshParams.value)
    return Object.keys(params).length
      ? { command_id: values.command_id, params }
      : { command_id: values.command_id }
  }
  if (connectorType.value === 'ansible') {
    return {
      playbook: values.playbook,
      limit: values.limit,
      extra_vars: values.extra_vars ?? {},
      timeout_seconds: values.timeout_seconds ?? 300,
    }
  }
  return { operation: values.operation, target: values.target }
}
const save = async () => {
  if (!(await formRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  const { service_id: serviceId, key, label, description, icon, connector, ...flags } = form.value
  if (!serviceId || !key || !connector) return
  const payload: ActionInput = {
    key: key.trim(),
    label: label.trim(),
    description: blankToNull(description),
    icon: blankToNull(icon),
    connector,
    ...flags,
    config: buildConfig(),
    allowed_parameters_schema: props.action?.allowed_parameters_schema ?? {},
  }
  try {
    if (props.action) {
      await api.updateAction(serviceId, props.action.key, payload)
      Notify.create({ type: 'positive', message: t('notify.actionUpdated') })
    } else {
      await api.createAction(serviceId, payload)
      Notify.create({ type: 'positive', message: t('notify.actionCreated') })
    }
    open.value = false
    emit('saved', serviceId)
  } catch (error) {
    notifyApiError(error, t('notify.actionSaveFailed'))
  }
}
</script>
<template>
  <q-dialog v-model="open">
    <q-card class="form-card form-card-wide">
      <q-card-section>
        <div class="text-h6">
          {{ editing ? t('pages.catalog.editActionTitle') : t('pages.catalog.newActionTitle') }}
        </div>
      </q-card-section>
      <q-form ref="formRef">
        <q-card-section class="q-gutter-md scroll-section">
          <q-select
            v-model="form.service_id"
            :options="serviceOptions"
            emit-value
            map-options
            outlined
            :disable="editing"
            :label="t('pages.catalog.serviceLabel')"
            :rules="[required]"
          />
          <q-input
            v-model="form.key"
            outlined
            :label="t('pages.catalog.keyLabel')"
            :disable="editing"
            :rules="[required]"
          />
          <q-input v-model="form.label" outlined :label="t('pages.catalog.labelLabel')" :rules="[required]" />
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
            :model-value="form.connector"
            :options="connectorChoices"
            emit-value
            map-options
            outlined
            :label="t('pages.catalog.actionConnectorLabel')"
            :hint="
              connectorChoices.length
                ? t('pages.catalog.actionConnectorHint')
                : t('pages.catalog.noConnectorsForCapability')
            "
            :rules="[required]"
            @update:model-value="onConnectorChange"
          />
          <template v-if="connectorType === 'portainer'">
            <q-select
              v-model="portainerOperation"
              :options="portainerOperations"
              outlined
              :label="t('pages.catalog.operationLabel')"
              :rules="[required]"
            />
            <q-select
              v-model="portainerTarget"
              :options="portainerTargets"
              :option-label="(value) => t(`enums.portainerTarget.${value}`)"
              outlined
              :label="t('pages.catalog.targetLabel')"
              :hint="t('pages.catalog.targetHint')"
              :rules="[required]"
            />
          </template>
          <template v-else-if="connectorType === 'ansible'">
            <q-select
              v-model="ansiblePlaybook"
              :options="ansiblePlaybooks"
              outlined
              :label="t('pages.catalog.ansiblePlaybookLabel')"
              :rules="[required]"
            />
            <q-input
              v-model="ansibleLimit"
              outlined
              :label="t('pages.catalog.ansibleLimitLabel')"
              :hint="t('pages.catalog.ansibleLimitHint')"
              :rules="[required]"
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
          <template v-else-if="connectorType === 'ssh'">
            <q-select
              v-model="sshCommand"
              :options="sshCommands"
              outlined
              :label="t('pages.catalog.sshCommandLabel')"
              :hint="t('pages.catalog.sshCommandHint')"
              :rules="[required]"
            />
            <q-input
              v-model="sshParams"
              outlined
              :label="t('pages.catalog.sshParamsLabel')"
              :hint="t('pages.catalog.sshParamsHint')"
            />
          </template>
          <q-select
            v-model="form.risk_level"
            :options="riskOptions"
            emit-value
            map-options
            outlined
            :label="t('pages.catalog.riskLabel')"
            :rules="[required]"
          />
          <q-toggle v-model="form.requires_confirmation" :label="t('pages.catalog.requiresConfirmation')" />
          <q-toggle v-model="form.unattended" :label="t('pages.catalog.unattendedLabel')" />
          <q-toggle v-model="form.enabled" :label="t('pages.catalog.enabledLabel')" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="primary" no-caps :label="t('common.save')" @click="save" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
