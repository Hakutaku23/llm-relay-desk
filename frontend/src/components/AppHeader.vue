<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import LanguageSwitcher from '@/components/LanguageSwitcher.vue'

const { t } = useI18n()
</script>

<template>
  <header class="topbar">
    <div>
      <span class="eyebrow">{{ t('header.eyebrow') }}</span>
      <strong>{{ t('header.title') }}</strong>
    </div>
    <div class="header-actions">
      <span class="environment-badge">{{ t('header.environment') }}</span>
      <LanguageSwitcher />
    </div>
  </header>
</template>
