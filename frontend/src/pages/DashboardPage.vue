<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Notify } from 'quasar'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ServiceCard from '@/components/ServiceCard.vue'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useServicesStore } from '@/stores/services'
import { useAuthStore } from '@/stores/auth'
import { notifyApiError } from '@/api/notify'
const services = useServicesStore()
const auth = useAuthStore()
const { t } = useI18n()
const search = ref('')
const group = ref<string | null>(null)
const environment = ref<string | null>(null)
const groups = computed(() => [...new Set(services.items.map((service) => service.group_name))])
const environments = computed(() => [...new Set(services.items.map((service) => service.environment))])
const filtered = computed(() =>
  services.items.filter(
    (service) =>
      (!group.value || service.group_name === group.value) &&
      (!environment.value || service.environment === environment.value) &&
      `${service.name} ${service.description ?? ''}`
        .toLocaleLowerCase()
        .includes(search.value.toLocaleLowerCase()),
  ),
)
const refresh = async (id: string, silent = false) => {
  try {
    await services.refresh(id)
    if (!silent) Notify.create({ type: 'positive', message: t('notify.statusUpdated') })
  } catch (error) {
    if (!silent) notifyApiError(error, t('notify.statusUpdateFailed'))
  }
}
const refreshAll = async (silent = false) => {
  await Promise.all(services.items.map((service) => refresh(service.id, silent)))
}
const { intervalMs: refreshIntervalMs } = useAutoRefresh(() => {
  if (auth.isOperator) return refreshAll(true)
})
onMounted(async () => {
  // El backend admite hasta 100 por página (CR-092); el Dashboard no pagina todavía, así que pide
  // el máximo en vez del límite por defecto (20) para no ocultar servicios en silencio.
  await services.fetch({ limit: '100' })
  if (auth.isOperator) await refreshAll(true)
})
</script>
<template>
  <AppLayout
    ><q-page class="page"
      ><header class="page-header">
        <div>
          <p class="eyebrow">{{ t('pages.dashboard.eyebrow') }}</p>
          <h1>{{ t('pages.dashboard.title') }}</h1>
          <p>
            {{ t('pages.dashboard.description') }}
          </p>
        </div>
        <div class="row items-center q-gutter-sm">
          <AutoRefreshSelect v-model="refreshIntervalMs" :disable="!auth.isOperator" /><q-btn
            color="primary"
            no-caps
            icon="refresh"
            :label="t('pages.dashboard.updateAll')"
            :loading="services.loading"
            :disable="!auth.isOperator"
            @click="() => refreshAll()"
          />
        </div>
      </header>
      <section class="filters" :aria-label="t('pages.dashboard.filtersAria')">
        <q-input
          v-model="search"
          outlined
          dense
          clearable
          :label="t('pages.dashboard.searchLabel')"
          class="search"
          ><template #prepend><q-icon name="search" /></template></q-input
        ><q-select
          v-model="group"
          :options="groups"
          outlined
          dense
          clearable
          :label="t('pages.dashboard.groupLabel')" /><q-select
          v-model="environment"
          :options="environments"
          outlined
          dense
          clearable
          :label="t('pages.dashboard.environmentLabel')"
        />
      </section>
      <q-banner v-if="services.error" class="error-banner" rounded inline-actions
        ><template #avatar><q-icon name="error" /></template>{{ services.error
        }}<template #action
          ><q-btn flat :label="t('common.retry')" @click="services.fetch({ limit: '100' })" /></template
      ></q-banner>
      <q-banner v-if="services.total > services.items.length" class="q-mb-md" rounded dense
        >{{ t('pages.dashboard.showingCount', { shown: services.items.length, total: services.total }) }}</q-banner
      >
      <section v-if="services.loading" class="services-grid" :aria-label="t('pages.dashboard.loadingAria')">
        <q-skeleton v-for="item in 4" :key="item" height="200px" class="skeleton-card" />
      </section>
      <section v-else-if="filtered.length" class="services-grid" :aria-label="t('pages.dashboard.gridAria')">
        <ServiceCard
          v-for="service in filtered"
          :key="service.id"
          :service="service"
          :status="services.statuses[service.id]"
          :actions="services.actionsByService[service.id]"
          :can-refresh="auth.isOperator"
        />
      </section>
      <section v-else class="empty-state">
        <q-icon name="filter_alt_off" size="48px" />
        <h2>{{ t('pages.dashboard.emptyTitle') }}</h2>
        <p>{{ t('pages.dashboard.emptyHint') }}</p>
        <q-btn
          flat
          color="primary"
          :label="t('pages.dashboard.clearFilters')"
          @click="
            () => {
              search = ''
              group = null
              environment = null
            }
          "
        /></section></q-page
  ></AppLayout>
</template>
