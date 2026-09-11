<script setup lang="ts">
import { computed, ref } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { api } from '@/api/capatazApi'
import { notifyApiError } from '@/api/notify'
import type { Resource, ResourceType } from '@/api/types'
import { useCatalogStore } from '@/stores/catalog'
import { MAX_RESOURCE_BYTES, bytesToBase64, resourceTypes } from '@/utils/catalog'
const catalog = useCatalogStore()
const { t, locale } = useI18n()
const formRef = ref<QForm>()
const required = (value: unknown) => !!value || t('common.requiredField')
const dialog = ref(false)
// Set when replacing an existing resource's content; undefined when creating a new one.
const replacing = ref<Resource>()
const id = ref('')
const type = ref<ResourceType>('secret')
const description = ref('')
const file = ref<File | null>(null)
const content = ref('')
const confirmDelete = ref(false)
const toDelete = ref<Resource>()
const typeOptions = computed(() =>
  resourceTypes.map((value) => ({ label: t(`enums.resourceType.${value}`), value })),
)

/** Where the stored content came from; never the content itself (the API doesn't return it). */
const sourceLabel = ({ source }: Resource): string => {
  if (typeof source.file === 'string') return t('pages.catalog.resources.source.file', { name: source.file })
  if (typeof source.env === 'string') return t('pages.catalog.resources.source.env', { name: source.env })
  if (source.inline) return t('pages.catalog.resources.source.inline')
  return t('pages.catalog.resources.source.upload')
}
const updatedAt = (resource: Resource) =>
  resource.updated_at ? new Date(resource.updated_at).toLocaleString(locale.value) : ''

const openDialog = (resource?: Resource) => {
  replacing.value = resource
  id.value = resource?.id ?? ''
  type.value = resource?.type ?? 'secret'
  description.value = resource?.description ?? ''
  file.value = null
  content.value = ''
  dialog.value = true
}
const encodeContent = async (): Promise<string | undefined> => {
  const bytes = file.value
    ? new Uint8Array(await file.value.arrayBuffer())
    : content.value
      ? new TextEncoder().encode(content.value)
      : undefined
  if (!bytes?.length) {
    Notify.create({ type: 'negative', message: t('pages.catalog.resources.contentRequired') })
    return undefined
  }
  if (bytes.length > MAX_RESOURCE_BYTES) {
    Notify.create({ type: 'negative', message: t('pages.catalog.resources.tooLarge') })
    return undefined
  }
  return bytesToBase64(bytes)
}
const save = async () => {
  if (!(await formRef.value?.validate())) {
    Notify.create({ type: 'negative', message: t('common.completeRequiredFields') })
    return
  }
  const contentBase64 = await encodeContent()
  if (!contentBase64) return
  const resource = replacing.value
  const trimmedDescription = description.value.trim() || null
  try {
    if (resource) {
      await api.replaceResourceContent(resource.id, {
        content_base64: contentBase64,
        description: trimmedDescription,
      })
    } else {
      await api.createResource({
        id: id.value.trim(),
        type: type.value,
        description: trimmedDescription,
        content_base64: contentBase64,
      })
    }
    // Don't keep the plaintext around in the component once it has been sent.
    content.value = ''
    file.value = null
    dialog.value = false
    await catalog.fetchResources()
    Notify.create({ type: 'positive', message: t('notify.resourceSaved') })
  } catch (error) {
    notifyApiError(error, t('notify.resourceSaveFailed'))
  }
}
const requestRemove = (resource: Resource) => {
  toDelete.value = resource
  confirmDelete.value = true
}
const remove = async () => {
  const resource = toDelete.value
  if (!resource) return
  try {
    await api.deleteResource(resource.id)
    await catalog.fetchResources()
    Notify.create({ type: 'positive', message: t('notify.resourceDeleted') })
  } catch (error) {
    notifyApiError(error, t('notify.resourceDeleteFailed'))
  }
}
</script>
<template>
  <article class="panel">
    <div class="row items-start justify-between q-gutter-sm">
      <div>
        <h2>{{ t('pages.catalog.resources.title') }}</h2>
        <p class="panel-intro">{{ t('pages.catalog.resources.intro') }}</p>
      </div>
      <q-btn
        color="primary"
        no-caps
        icon="add"
        :label="t('pages.catalog.resources.newResource')"
        @click="openDialog()"
      />
    </div>
    <q-list v-if="catalog.resources.length" separator bordered>
      <q-item v-for="resource in catalog.resources" :key="resource.id">
        <q-item-section>
          <q-item-label>{{ resource.id }}</q-item-label>
          <q-item-label caption>
            {{ t(`enums.resourceType.${resource.type}`) }} ·
            {{ t('pages.catalog.resources.sizeBytes', { size: resource.size }) }} ·
            {{ t('pages.catalog.resources.fingerprintLabel') }} {{ resource.fingerprint }} ·
            {{ sourceLabel(resource)
            }}<template v-if="updatedAt(resource)"> · {{ updatedAt(resource) }}</template>
          </q-item-label>
          <q-item-label v-if="resource.description" caption>{{ resource.description }}</q-item-label>
        </q-item-section>
        <q-item-section side class="row q-gutter-xs">
          <q-btn
            flat
            round
            icon="upload_file"
            :aria-label="t('pages.catalog.resources.replaceAria', { id: resource.id })"
            @click="openDialog(resource)"
          />
          <q-btn
            flat
            round
            color="negative"
            icon="delete"
            :aria-label="t('pages.catalog.resources.deleteAria', { id: resource.id })"
            @click="requestRemove(resource)"
          />
        </q-item-section>
      </q-item>
    </q-list>
    <p v-else class="text-caption">{{ t('pages.catalog.resources.empty') }}</p>
    <q-dialog v-model="dialog">
      <q-card class="form-card form-card-wide">
        <q-card-section>
          <div class="text-h6">
            {{
              replacing
                ? t('pages.catalog.resources.replaceTitle', { id: replacing.id })
                : t('pages.catalog.resources.newTitle')
            }}
          </div>
        </q-card-section>
        <q-form ref="formRef">
          <q-card-section class="q-gutter-md scroll-section">
            <q-input
              v-model="id"
              outlined
              :label="t('pages.catalog.idLabel')"
              :disable="!!replacing"
              :rules="[required]"
            />
            <q-select
              v-model="type"
              :options="typeOptions"
              emit-value
              map-options
              outlined
              :disable="!!replacing"
              :label="t('pages.catalog.connectors.typeLabel')"
            />
            <q-input v-model="description" outlined :label="t('pages.catalog.descriptionLabel')" />
            <q-file v-model="file" outlined clearable :label="t('pages.catalog.resources.fileLabel')" />
            <q-input
              v-model="content"
              outlined
              type="textarea"
              autogrow
              :disable="!!file"
              :label="t('pages.catalog.resources.contentLabel')"
              :hint="t('pages.catalog.resources.contentHint')"
              input-class="resource-content-input"
            />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat :label="t('common.cancel')" />
            <q-btn color="primary" no-caps :label="t('common.save')" @click="save" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
    <ConfirmDialog
      v-model="confirmDelete"
      :title="t('pages.catalog.resources.deleteConfirmTitle')"
      :message="t('pages.catalog.resources.deleteConfirmMessage', { id: toDelete?.id ?? '' })"
      @confirm="remove"
    />
  </article>
</template>
