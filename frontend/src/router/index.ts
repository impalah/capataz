import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AuditPage from '@/pages/AuditPage.vue'
import AuthCallbackPage from '@/pages/AuthCallbackPage.vue'
import CatalogPage from '@/pages/CatalogPage.vue'
import DashboardPage from '@/pages/DashboardPage.vue'
import ExecutionPage from '@/pages/ExecutionPage.vue'
import ExecutionsPage from '@/pages/ExecutionsPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import ServiceDetailPage from '@/pages/ServiceDetailPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginPage, meta: { public: true } },
    { path: '/auth/callback', name: 'auth-callback', component: AuthCallbackPage, meta: { public: true } },
    { path: '/', name: 'dashboard', component: DashboardPage },
    { path: '/services/:id', name: 'service', component: ServiceDetailPage, props: true },
    { path: '/executions', name: 'executions', component: ExecutionsPage },
    { path: '/executions/:id', name: 'execution', component: ExecutionPage, props: true },
    { path: '/catalog', name: 'catalog', component: CatalogPage, meta: { admin: true } },
    { path: '/audit', name: 'audit', component: AuditPage, meta: { admin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  await auth.load()
  if (!auth.devMockEnabled && !auth.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return { name: 'dashboard' }
  return true
})

export default router
