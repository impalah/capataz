<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Dark, Notify, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LanguageSelector from '@/components/LanguageSelector.vue'
import type { Role } from '@/api/types'
const auth = useAuthStore()
const route = useRoute()
const $q = useQuasar()
const { t } = useI18n()
const isMobile = computed(() => $q.screen.lt.md)
const drawer = ref(true)
const nav = computed(() => [
  { label: t('nav.services'), icon: 'grid_view', to: '/' },
  { label: t('nav.executions'), icon: 'receipt_long', to: '/executions' },
  ...(auth.isAdmin
    ? [
        { label: t('nav.catalog'), icon: 'inventory_2', to: '/catalog' },
        { label: t('nav.audit'), icon: 'policy', to: '/audit' },
      ]
    : []),
])
const roleLabel = (role: Role): string => t(`enums.role.${role.replace('capataz-', '')}`)
const THEME_STORAGE_KEY = 'capataz.theme'
const DRAWER_STORAGE_KEY = 'capataz.drawerOpen'
onMounted(() => {
  // Every page wraps itself in <AppLayout> (there's no single shared layout instance kept
  // alive across routes), so this onMounted re-runs on every navigation. Without reading back
  // a stored choice, that would silently force dark mode back on after every single click.
  Dark.set(localStorage.getItem(THEME_STORAGE_KEY) !== 'light')
  // The fold preference only applies to non-mobile widths: on mobile the drawer is always an
  // overlay and should start closed regardless of what was last chosen on desktop.
  drawer.value = isMobile.value ? false : localStorage.getItem(DRAWER_STORAGE_KEY) !== 'closed'
  auth.load().catch(() => undefined)
})
watch(drawer, (value) => {
  if (!isMobile.value) localStorage.setItem(DRAWER_STORAGE_KEY, value ? 'open' : 'closed')
})
const toggleTheme = (): void => {
  Dark.toggle()
  localStorage.setItem(THEME_STORAGE_KEY, Dark.isActive ? 'dark' : 'light')
}
watch(
  () => auth.unauthorized,
  (value) => {
    if (value && !auth.devMockEnabled)
      Notify.create({
        type: 'warning',
        message: t('layout.sessionExpired'),
        timeout: 0,
        actions: [
          {
            label: t('layout.login'),
            color: 'white',
            handler: () => {
              auth.startLogin(route.fullPath).catch(() => undefined)
            },
          },
        ],
      })
  },
)
</script>
<template>
  <q-layout view="hHh Lpr fFf" class="app-layout">
    <a class="skip-link" href="#main-content">{{ t('layout.skipToContent') }}</a>
    <q-header bordered class="header"
      ><q-toolbar
        ><q-btn
          flat
          dense
          round
          icon="menu"
          :aria-label="drawer ? t('layout.foldNav') : t('layout.unfoldNav')"
          @click="drawer = !drawer"
        /><RouterLink class="brand" to="/" :aria-label="t('layout.brandHome')"
          ><svg viewBox="0 0 64 64" aria-hidden="true">
            <path
              d="M10 19 L19 14 L23 19 C26 17 29 16 32 16 C35 16 38 17 41 19 L45 14 L54 19 L52 42 C51 51 43 56 32 56 C21 56 13 51 12 42 Z"
              fill="var(--color-brand)"
            /><circle cx="23" cy="35" r="10" fill="white" /><circle cx="41" cy="35" r="10" fill="white" /><circle
              cx="23"
              cy="35"
              r="4"
              fill="var(--color-brand)"
            /><circle cx="41" cy="35" r="4" fill="var(--color-brand)" /><path
              d="M32 39 L36 44 L32 48 L28 44 Z"
              fill="white"
            /></svg
          ><span>capataz</span></RouterLink
        ><q-space /><q-btn
          flat
          round
          :icon="Dark.isActive ? 'light_mode' : 'dark_mode'"
          :aria-label="Dark.isActive ? t('layout.activateLightMode') : t('layout.activateDarkMode')"
          @click="toggleTheme"
        /><LanguageSelector /><q-btn
          flat
          dense
          icon="account_circle"
          :label="auth.displayName"
          class="q-ml-sm"
          data-testid="account-menu"
          ><q-menu
            ><q-list style="min-width: 190px"
              ><template v-if="auth.devMockEnabled"
                ><q-item-label header>{{ t('layout.devModeHeader') }}</q-item-label
                ><q-item
                  v-for="role in ['capataz-viewer', 'capataz-operator', 'capataz-admin'] as Role[]"
                  :key="role"
                  v-close-popup
                  clickable
                  @click="auth.selectDevRole(role)"
                  ><q-item-section avatar
                    ><q-icon
                      :name="
                        auth.highestRole === role ? 'radio_button_checked' : 'radio_button_unchecked'
                      " /></q-item-section
                  ><q-item-section>{{ roleLabel(role) }}</q-item-section></q-item
                ></template
              ><template v-else
                ><q-item-label header>{{ auth.displayName }}</q-item-label
                ><q-item-label caption class="q-px-md q-pb-sm">{{
                  roleLabel(auth.highestRole)
                }}</q-item-label
                ><q-item v-close-popup clickable @click="auth.logout()"
                  ><q-item-section avatar><q-icon name="logout" /></q-item-section
                  ><q-item-section>{{ t('layout.logout') }}</q-item-section></q-item
                ></template
              ></q-list
            ></q-menu
          ></q-btn
        ></q-toolbar
      ></q-header
    >
    <q-drawer v-model="drawer" bordered :width="248" class="drawer"
      ><q-list padding
        ><q-item-label header class="drawer-title">{{ t('layout.operationHeader') }}</q-item-label
        ><q-item v-for="item in nav" :key="item.to" :to="item.to" exact clickable active-class="nav-active"
          ><q-item-section avatar><q-icon :name="item.icon" /></q-item-section
          ><q-item-section>{{ item.label }}</q-item-section></q-item
        ></q-list
      >
      <div class="drawer-foot">
        <q-chip dense outline icon="verified_user">{{ auth.displayName }}</q-chip>
        <p>{{ t('layout.authorizationNote') }}</p>
      </div></q-drawer
    >
    <q-page-container
      ><main id="main-content"><slot /></main
    ></q-page-container>
  </q-layout>
</template>
