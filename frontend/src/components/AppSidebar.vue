<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <aside class="sidebar">
    <div class="brand-mark" aria-hidden="true">LR</div>
    <div class="brand-copy">
      <strong>{{ t('app.name') }}</strong>
      <span>{{ t('app.tagline') }}</span>
    </div>
    <nav :aria-label="t('navigation.label')">
      <RouterLink class="nav-link" to="/">{{ t('navigation.dashboard') }}</RouterLink>
      <RouterLink class="nav-link" to="/status">{{ t('navigation.status') }}</RouterLink>
      <RouterLink class="nav-link" to="/settings">{{ t('navigation.settings') }}</RouterLink>
      <RouterLink class="nav-link" to="/api-test">{{ t('navigation.apiTest') }}</RouterLink>
      <a class="nav-link" href="/ui-legacy/">{{ t('navigation.legacy') }}</a>
      <a class="nav-link" href="/monitor/">{{ t('navigation.monitor') }}</a>
    </nav>
  </aside>
</template>
