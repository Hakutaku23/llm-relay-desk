<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { persistLocale, type SupportedLocale } from '@/i18n/locale'

const { locale, t } = useI18n({ useScope: 'global' })

const selectedLocale = computed<SupportedLocale>({
  get: () => locale.value as SupportedLocale,
  set: (value) => {
    locale.value = value
    persistLocale(value)
  },
})
</script>

<template>
  <label class="language-switcher">
    <span>{{ t('language.label') }}</span>
    <select v-model="selectedLocale" :aria-label="t('language.label')">
      <option value="zh-CN">{{ t('language.zhCN') }}</option>
      <option value="en-US">{{ t('language.enUS') }}</option>
    </select>
  </label>
</template>
