<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const errorMessage = ref('')
onMounted(async () => {
  try {
    const redirectPath = await auth.completeLogin(window.location.href)
    await router.replace(redirectPath)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : t('pages.authCallback.defaultError')
  }
})
</script>
<template>
  <div class="auth-shell">
    <div class="auth-card">
      <h1>Capataz</h1>
      <template v-if="errorMessage"
        ><p class="error-banner">{{ errorMessage }}</p>
        <q-btn
          color="primary"
          no-caps
          :label="t('pages.authCallback.retry')"
          @click="auth.startLogin('/')" /></template
      ><template v-else
        ><q-spinner size="32px" color="primary" />
        <p>{{ t('pages.authCallback.completing') }}</p></template
      >
    </div>
  </div>
</template>
