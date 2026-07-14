import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import DashboardView from '@/views/DashboardView.vue'
import NotFoundView from '@/views/NotFoundView.vue'

declare module 'vue-router' {
  interface RouteMeta {
    titleKey?: 'routes.dashboard' | 'routes.notFound'
  }
}

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: DashboardView, meta: { titleKey: 'routes.dashboard' } },
  { path: '/dashboard', redirect: '/' },
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
