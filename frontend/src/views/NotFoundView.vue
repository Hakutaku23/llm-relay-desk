<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <section class="page not-found" aria-labelledby="not-found-title">
    <p class="eyebrow">{{ t('notFound.code') }}</p>
    <h1 id="not-found-title">{{ t('notFound.title') }}</h1>
    <p>{{ t('notFound.body') }}</p>
    <RouterLink class="text-link" to="/">{{ t('notFound.returnToDashboard') }}</RouterLink>
  </section>
</template>
