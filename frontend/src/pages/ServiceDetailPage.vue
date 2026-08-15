<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/layouts/AppLayout.vue'
import ServiceStatusBadge from '@/components/ServiceStatusBadge.vue'
import ExecutionStatusBadge from '@/components/ExecutionStatusBadge.vue'
import CriticalConfirmDialog from '@/components/CriticalConfirmDialog.vue'
import AutoRefreshSelect from '@/components/AutoRefreshSelect.vue'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useActionExecution } from '@/composables/useActionExecution'
import { useServicesStore } from '@/stores/services'
import { useExecutionsStore } from '@/stores/executions'
import { useAuthStore } from '@/stores/auth'
import { notifyApiError } from '@/api/notify'
const props = defineProps<{ id: string }>()
const services = useServicesStore()
const executions = useExecutionsStore()
const auth = useAuthStore()
const { t, locale } = useI18n()
const refreshing = ref(false)
const loadService = async (id: string) => {
  await services.fetchDetail(id)
  await executions.fetch({ service_id: id })
  void refreshStatus()
}
onMounted(() => loadService(props.id))
// Vue Router reuses this component instance when navigating between two /services/:id URLs
// instead of remounting it, so onMounted alone would leave the previous service on screen (CR-072).
watch(
  () => props.id,
  (id) => void loadService(id),
)
const refreshStatus = async (silent = false) => {
  refreshing.value = true
  try {
    await services.refresh(props.id)
  } catch (error) {
    if (!silent) notifyApiError(error, t('notify.statusUpdateFailed'))
  } finally {
    refreshing.value = false
  }
}
const { intervalMs: refreshIntervalMs } = useAutoRefresh(() => {
  if (auth.isOperator) return refreshStatus(true)
})
const { pending, confirmOpen, requestAction, confirmPending } = useActionExecution(
  () => props.id,
  () => void refreshStatus(true),
)
</script>
<template>
  <AppLayout
    ><q-page class="page"
      ><q-btn flat icon="arrow_back" :label="t('pages.serviceDetail.back')" to="/" class="back-link" /><q-banner
        v-if="services.error"
        class="error-banner"
        rounded
        >{{ services.error }}</q-banner
      >
      <div v-else-if="services.selected" class="detail">
        <header class="detail-header">
          <div>
            <p class="eyebrow">{{ services.selected.group_name }} · {{ services.selected.environment }}</p>
            <h1><q-icon :name="services.selected.icon ?? 'dns'" /> {{ services.selected.name }}</h1>
            <p>{{ services.selected.description }}</p>
          </div>
          <div class="row items-center q-gutter-x-sm">
            <ServiceStatusBadge :status="services.statuses[props.id]?.status" /><AutoRefreshSelect
              v-model="refreshIntervalMs"
              :disable="!auth.isOperator"
            /><q-btn
              flat
              round
              icon="refresh"
              :loading="refreshing"
              :aria-label="t('pages.serviceDetail.updateStatus')"
              @click="() => refreshStatus()"
              ><q-tooltip>{{ t('pages.serviceDetail.updateStatus') }}</q-tooltip></q-btn
            >
          </div>
        </header>
        <section class="detail-grid">
          <article class="panel">
            <h2>{{ t('pages.serviceDetail.containerStatus') }}</h2>
            <q-banner v-if="services.statuses[props.id]?.error" class="error-banner" dense rounded
              ><template #avatar><q-icon name="error" color="negative" /></template
              >{{ services.statuses[props.id]?.error }}</q-banner
            >
            <q-list separator
              ><q-item
                v-for="container in services.statuses[props.id]?.containers ?? []"
                :key="container.name"
                ><q-item-section avatar
                  ><q-icon
                    :name="container.running ? 'check_circle' : 'cancel'"
                    :color="container.running ? 'positive' : 'negative'" /></q-item-section
                ><q-item-section
                  ><q-item-label>{{ container.name }}</q-item-label
                  ><q-item-label caption
                    >{{ t('pages.serviceDetail.health') }}:
                    {{
                      container.healthy === null || container.healthy === undefined
                        ? t('pages.serviceDetail.healthUnknown')
                        : container.healthy
                          ? t('pages.serviceDetail.healthOk')
                          : t('pages.serviceDetail.healthFail')
                    }}</q-item-label
                  ></q-item-section
                ><q-item-section side>{{
                  container.running ? t('pages.serviceDetail.running') : t('pages.serviceDetail.stopped')
                }}</q-item-section></q-item
              ><q-item v-if="!services.statuses[props.id]?.containers?.length"
                ><q-item-section>{{ t('pages.serviceDetail.noStatusYet') }}</q-item-section></q-item
              ></q-list
            >
          </article>
          <article class="panel">
            <h2>{{ t('pages.serviceDetail.allowedActions') }}</h2>
            <p class="panel-intro">{{ t('pages.serviceDetail.authNote') }}</p>
            <q-list separator
              ><q-item v-for="action in services.actions" :key="action.id"
                ><q-item-section avatar><q-icon :name="action.icon ?? 'play_arrow'" /></q-item-section
                ><q-item-section
                  ><q-item-label>{{ action.label }}</q-item-label
                  ><q-item-label caption
                    >{{ t(`enums.actionType.${action.action_type}`) }}
                    {{ t('pages.serviceDetail.riskPrefix') }}
                    {{ t(`enums.riskLevel.${action.risk_level}`) }}</q-item-label
                  ></q-item-section
                ><q-item-section side
                  ><q-btn
                    color="primary"
                    no-caps
                    :label="t('pages.serviceDetail.execute')"
                    :disable="!auth.canExecute(action.risk_level) || !action.enabled"
                    @click="requestAction(action)" /></q-item-section></q-item
            ></q-list>
          </article>
          <article class="panel">
            <h2>{{ t('pages.serviceDetail.observability') }}</h2>
            <q-list
              ><q-item
                v-for="(link, label) in services.links"
                :key="label"
                :href="link"
                target="_blank"
                rel="noopener noreferrer"
                clickable
                ><q-item-section avatar><q-icon name="open_in_new" /></q-item-section
                ><q-item-section>{{ label }}</q-item-section></q-item
              ><q-item
                v-if="services.selected.service_url"
                :href="services.selected.service_url"
                target="_blank"
                rel="noopener noreferrer"
                clickable
                ><q-item-section avatar><q-icon name="language" /></q-item-section
                ><q-item-section>{{ t('pages.serviceDetail.openService') }}</q-item-section></q-item
              ></q-list
            >
          </article>
          <article class="panel">
            <h2>{{ t('pages.serviceDetail.latestExecutions') }}</h2>
            <q-list separator
              ><q-item
                v-for="execution in executions.items.slice(0, 4)"
                :key="execution.id"
                :to="`/executions/${execution.id}`"
                clickable
                ><q-item-section
                  ><q-item-label>{{
                    execution.action_key ?? t('pages.serviceDetail.fallbackAction')
                  }}</q-item-label
                  ><q-item-label caption>{{
                    new Date(execution.requested_at).toLocaleString(locale)
                  }}</q-item-label></q-item-section
                ><q-item-section side
                  ><ExecutionStatusBadge :status="execution.status" /></q-item-section></q-item
              ><q-item v-if="!executions.items.length"
                ><q-item-section>{{ t('pages.serviceDetail.noExecutionsYet') }}</q-item-section></q-item
              ></q-list
            >
          </article>
        </section>
      </div>
      <q-inner-loading :showing="services.loading"><q-spinner size="44px" /></q-inner-loading
      ><CriticalConfirmDialog
        v-model="confirmOpen"
        :action="pending"
        :service="services.selected"
        @confirm="confirmPending" /></q-page
  ></AppLayout>
</template>
