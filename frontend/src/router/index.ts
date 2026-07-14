import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import DashboardView from '@/views/DashboardView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import SettingsView from '@/views/SettingsView.vue'
import StatusView from '@/views/StatusView.vue'
import ApiTestView from '@/views/ApiTestView.vue'
import PromptsView from '@/views/PromptsView.vue'
import TaskIsolationView from '@/views/TaskIsolationView.vue'
import SubtitlesView from '@/views/SubtitlesView.vue'

declare module 'vue-router' {
  interface RouteMeta {
    titleKey?: 'routes.dashboard' | 'routes.status' | 'routes.settings' | 'routes.apiTest' | 'routes.prompts' | 'routes.taskIsolation' | 'routes.subtitles' | 'routes.notFound'
  }
}

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: DashboardView, meta: { titleKey: 'routes.dashboard' } },
  { path: '/dashboard', redirect: '/' },
  { path: '/status', name: 'status', component: StatusView, meta: { titleKey: 'routes.status' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { titleKey: 'routes.settings' } },
  { path: '/api-test', name: 'api-test', component: ApiTestView, meta: { titleKey: 'routes.apiTest' } },
  { path: '/prompts', name: 'prompts', component: PromptsView, meta: { titleKey: 'routes.prompts' } },
  { path: '/task-isolation', name: 'task-isolation', component: TaskIsolationView, meta: { titleKey: 'routes.taskIsolation' } },
  { path: '/subtitles', name: 'subtitles', component: SubtitlesView, meta: { titleKey: 'routes.subtitles' } },
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
