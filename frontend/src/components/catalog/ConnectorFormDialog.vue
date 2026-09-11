<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/capatazApi'
import { ApiError } from '@/api/client'
import { notifyApiError } from '@/api/notify'
import type { Connector, ConnectorType, Resource, ResourceType } from '@/api/types'
import { ansibleInventories, connectorTypes } from '@/utils/catalog'

type FieldKind = 'text' | 'number' | 'bool' | 'resource' | 'suffixes' | 'inventory'
interface FieldDef {
  key: string
  kind: FieldKind
  required?: boolean
  resourceType?: ResourceType
  initial?: number | boolean
}
// Mirrors the per-type config models in api/src/capataz_api/domain/specs/connectors.py; the API
// validates the result again (including that each resource exists and has the expected type).
const FIELDS: Record<ConnectorType, FieldDef[]> = {
  portainer: [
    { key: 'url', kind: 'text', required: true },
    { key: 'token', kind: 'resource', required: true, resourceType: 'secret' },
    { key: 'verify_tls', kind: 'bool', initial: true },
  ],
  prometheus: [
    { key: 'url', kind: 'text', required: true },
    { key: 'token', kind: 'resource', resourceType: 'secret' },
    { key: 'verify_tls', kind: 'bool', initial: true },
  ],
  grafana: [{ key: 'url', kind: 'text', required: true }],
  loki: [{ key: 'url', kind: 'text', required: true }],
  http: [
    { key: 'allowed_host_suffixes', kind: 'suffixes' },
    { key: 'verify_tls', kind: 'bool', initial: true },
    { key: 'default_timeout_seconds', kind: 'number', initial: 5 },
  ],
  ansible: [
    { key: 'inventory', kind: 'inventory', required: true },
    { key: 'user', kind: 'text' },
    { key: 'private_key', kind: 'resource', required: true, resourceType: 'ssh_private_key' },
    { key: 'known_hosts', kind: 'resource', required: true, resourceType: 'known_hosts' },
    { key: 'vault_password', kind: 'resource', resourceType: 'secret' },
  ],
  ssh: [
    { key: 'host', kind: 'text', required: true },
    { key: 'port', kind: 'number', initial: 22 },
    { key: 'user', kind: 'text', required: true },
    { key: 'private_key', kind: 'resource', required: true, resourceType: 'ssh_private_key' },
    { key: 'known_hosts', kind: 'resource', required: true, resourceType: 'known_hosts' },
  ],
}

const props = defineProps<{ connector?: Connector; resources: Resource[] }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()
const { t } = useI18n()
const formRef = ref<QForm>()
const required = (value: unknown) =>
  (value !== null && value !== undefined && value !== '') || t('common.requiredField')
const id = ref('')
const type = ref<ConnectorType>('portainer')
const description = ref('')
// One map per input kind so every v-model binds a concretely typed value.
const text = ref<Record<string, string | null>>({})
const numbers = ref<Record<string, number | null>>({})
const flags = ref<Record<string, boolean>>({})
const editing = computed(() => !!props.connector)
const fields = computed(() => FIELDS[type.value])
const typeOptions = computed(() =>
  connectorTypes.map((value) => ({ label: t(`enums.connectorType.${value}`), value })),
)

const loadConfig = (connectorType: ConnectorType, config: Record<string, unknown> = {}) => {
  text.value = {}
  numbers.value = {}
  flags.value = {}
  for (const field of FIELDS[connectorType]) {
    const value = config[field.key]
    if (field.kind === 'bool')
      flags.value[field.key] = typeof value === 'boolean' ? value : field.initial === true
    else if (field.kind === 'number')
      numbers.value[field.key] =
        typeof value === 'number' ? value : typeof field.initial === 'number' ? field.initial : null
    else if (field.kind === 'suffixes') text.value[field.key] = Array.isArray(value) ? value.join(', ') : ''
    else text.value[field.key] = typeof value === 'string' ? value : ''
  }
}
const load = () => {
  id.value = props.connector?.id ?? ''
  type.value = props.connector?.type ?? 'portainer'
  description.value = props.connector?.description ?? ''
  loadConfig(type.value, props.connector?.config)
}
load()
watch(open, (isOpen) => {
  if (isOpen) load()
})
const onTypeChange = (value: ConnectorType) => {
  type.value = value
  loadConfig(value)
}
const resourceOptions = (resourceType?: ResourceType) =>
  props.resources
    .filter((resource) => resource.type === resourceType)
    .map((resource) => ({
      label: resource.description ? `${resource.id} — ${resource.description}` : resource.id,
      value: resource.id,
    }))
const fieldLabel = (field: FieldDef) => t(`pages.catalog.connectors.fields.${field.key}`)

const buildConfig = (): Record<string, unknown> => {
  const config: Record<string, unknown> = {}
  for (const field of fields.value) {
    if (field.kind === 'bool') {
      config[field.key] = flags.value[field.key] ?? false
    } else if (field.kind === 'number') {
      const value = numbers.value[field.key]
      if (value !== null && value !== undefined && `${value}` !== '') config[field.key] = Number(value)
    } else if (field.kind === 'suffixes') {
      config[field.key] = (text.value[field.key] ?? '')
        .split(',')
        .map((suffix) => suffix.trim())
        .filter(Boolean)
    } else {
      const value = (text.value[field.key] ?? '').trim()
      if (value) config[field.key] = value
    }
  }
  return config
}
const save = async () => {
  if (!(await formRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  const payload = {
    id: id.value.trim(),
    type: type.value,
    description: description.value.trim() || null,
    config: buildConfig(),
  }
  try {
    if (props.connector) await api.updateConnector(props.connector.id, payload, props.connector.version)
    else await api.createConnector(payload)
    open.value = false
    Notify.create({ type: 'positive', message: t('notify.connectorSaved') })
    emit('saved')
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && props.connector) {
      Notify.create({ type: 'negative', message: t('notify.connectorVersionConflict') })
    } else {
      notifyApiError(error, t('notify.connectorSaveFailed'))
    }
  }
}
</script>
<template>
  <q-dialog v-model="open">
    <q-card class="form-card form-card-wide">
      <q-card-section>
        <div class="text-h6">
          {{ editing ? t('pages.catalog.connectors.editTitle') : t('pages.catalog.connectors.newTitle') }}
        </div>
      </q-card-section>
      <q-form ref="formRef">
        <q-card-section class="q-gutter-md scroll-section">
          <q-input
            v-model="id"
            outlined
            :label="t('pages.catalog.idLabel')"
            :disable="editing"
            :rules="[required]"
          />
          <q-select
            :model-value="type"
            :options="typeOptions"
            emit-value
            map-options
            outlined
            :disable="editing"
            :label="t('pages.catalog.connectors.typeLabel')"
            @update:model-value="onTypeChange"
          />
          <q-input v-model="description" outlined :label="t('pages.catalog.descriptionLabel')" />
          <template v-for="field in fields" :key="`${type}-${field.key}`">
            <q-toggle v-if="field.kind === 'bool'" v-model="flags[field.key]" :label="fieldLabel(field)" />
            <q-input
              v-else-if="field.kind === 'number'"
              v-model.number="numbers[field.key]"
              type="number"
              outlined
              :label="fieldLabel(field)"
            />
            <q-select
              v-else-if="field.kind === 'resource'"
              v-model="text[field.key]"
              :options="resourceOptions(field.resourceType)"
              emit-value
              map-options
              outlined
              :clearable="!field.required"
              :label="fieldLabel(field)"
              :hint="
                t('pages.catalog.connectors.resourceHint', {
                  type: t(`enums.resourceType.${field.resourceType}`),
                })
              "
              :rules="field.required ? [required] : []"
            />
            <q-select
              v-else-if="field.kind === 'inventory'"
              v-model="text[field.key]"
              :options="ansibleInventories"
              outlined
              :label="fieldLabel(field)"
              :rules="[required]"
            />
            <q-input
              v-else
              v-model="text[field.key]"
              outlined
              :label="fieldLabel(field)"
              :hint="field.kind === 'suffixes' ? t('pages.catalog.connectors.suffixesHint') : undefined"
              :rules="field.required ? [required] : []"
            />
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="primary" no-caps :label="t('common.save')" @click="save" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
