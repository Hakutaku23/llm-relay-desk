<script setup lang="ts">
import { watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'

const route = useRoute()
const { locale, t } = useI18n({ useScope: 'global' })

watchEffect(() => {
  globalThis.document.documentElement.lang = locale.value
  globalThis.document.title = t(route.meta.titleKey ?? 'routes.dashboard')
})
</script>

<template>
  <div class="app-frame">
    <AppSidebar />
    <div class="app-workspace">
      <AppHeader />
      <main class="app-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>
