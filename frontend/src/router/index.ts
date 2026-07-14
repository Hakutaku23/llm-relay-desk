import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import DashboardView from '@/views/DashboardView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import SettingsView from '@/views/SettingsView.vue'
import StatusView from '@/views/StatusView.vue'

declare module 'vue-router' {
  interface RouteMeta {
    titleKey?: 'routes.dashboard' | 'routes.status' | 'routes.settings' | 'routes.notFound'
  }
}

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: DashboardView, meta: { titleKey: 'routes.dashboard' } },
  { path: '/dashboard', redirect: '/' },
  { path: '/status', name: 'status', component: StatusView, meta: { titleKey: 'routes.status' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { titleKey: 'routes.settings' } },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: NotFoundView,
    meta: { titleKey: 'routes.notFound' },
  },
]

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
