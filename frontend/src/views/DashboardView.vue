<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { useHealthStore } from '@/stores/health'

const health = useHealthStore()
const { t } = useI18n()
onMounted(() => void health.load())
</script>

<template>
  <section class="page" aria-labelledby="dashboard-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('dashboard.eyebrow') }}</p>
        <h1 id="dashboard-title">{{ t('dashboard.title') }}</h1>
      </div>
      <button class="refresh-button" type="button" :disabled="health.state === 'loading'" @click="health.load">
        {{ t('dashboard.refresh') }}
      </button>
    </div>

    <div v-if="health.state === 'idle' || health.state === 'loading'" class="status-panel" role="status">
      <span class="status-dot pending"></span>
      <div><strong>{{ t('dashboard.loadingTitle') }}</strong><p>{{ t('dashboard.loadingBody') }}</p></div>
    </div>

    <div v-else-if="health.state === 'healthy' && health.summary" class="status-panel healthy" role="status">
      <span class="status-dot healthy"></span>
      <div><strong>{{ t('dashboard.healthyTitle') }}</strong><p>{{ health.summary.service }} {{ health.summary.version }}</p></div>
    </div>

    <div v-else-if="health.state === 'malformed'" class="status-panel warning" role="alert">
      <span class="status-dot warning"></span>
      <div><strong>{{ t('dashboard.malformedTitle') }}</strong><p>{{ t('dashboard.malformedBody') }}</p></div>
    </div>

    <div v-else class="status-panel error" role="alert">
      <span class="status-dot error"></span>
      <div><strong>{{ t('dashboard.errorTitle') }}</strong><p>{{ t('dashboard.errorBody') }}</p></div>
    </div>

    <dl v-if="health.summary" class="details-list">
      <div><dt>{{ t('dashboard.model') }}</dt><dd>{{ health.summary.model ?? t('dashboard.notConfigured') }}</dd></div>
      <div><dt>{{ t('dashboard.protocol') }}</dt><dd>{{ health.summary.upstreamProtocol }}</dd></div>
      <div><dt>{{ t('dashboard.serviceState') }}</dt><dd>{{ t('dashboard.operational') }}</dd></div>
    </dl>
  </section>
</template>
