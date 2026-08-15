<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
const route = useRoute()
const { t } = useI18n()
const errorMessage = ref('')
const redirectPath = () => (typeof route.query.redirect === 'string' ? route.query.redirect : '/')
const retry = async () => {
  errorMessage.value = ''
  try {
    await auth.startLogin(redirectPath())
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : t('pages.login.defaultError')
  }
}
onMounted(retry)
</script>
<template>
  <div class="auth-shell">
    <div class="auth-card">
      <h1>Capataz</h1>
      <template v-if="errorMessage"
        ><p class="error-banner">{{ errorMessage }}</p>
        <q-btn color="primary" no-caps :label="t('pages.login.retry')" @click="retry" /></template
      ><template v-else
        ><q-spinner size="32px" color="primary" />
        <p>{{ t('pages.login.redirecting') }}</p></template
      >
    </div>
  </div>
</template>
