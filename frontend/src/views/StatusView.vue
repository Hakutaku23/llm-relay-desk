<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getHealth } from '@/api/health'
import { MalformedHealthResponseError, type HealthSummary } from '@/types/health'

const { t } = useI18n()
const state = ref<'loading' | 'ready' | 'malformed' | 'error'>('loading')
const status = ref<HealthSummary | null>(null)
async function refresh() {
  state.value = 'loading'
  try { status.value = await getHealth(); state.value = 'ready' }
  catch (error) { status.value = null; state.value = error instanceof MalformedHealthResponseError ? 'malformed' : 'error' }
}
onMounted(refresh)
</script>
<template>
  <section class="page">
    <header class="page-heading"><div><p class="eyebrow">{{ t('status.eyebrow') }}</p><h1>{{ t('status.title') }}</h1></div><button class="refresh-button" :disabled="state === 'loading'" @click="refresh">{{ t('status.refresh') }}</button></header>
    <div v-if="state === 'loading'" class="status-panel"><div class="status-dot"/><div><strong>{{ t('status.loading') }}</strong></div></div>
    <div v-else-if="state === 'malformed'" class="status-panel warning"><div class="status-dot warning"/><div><strong>{{ t('status.malformed') }}</strong><p>{{ t('status.malformedBody') }}</p></div></div>
    <div v-else-if="state === 'error'" class="status-panel error"><div class="status-dot error"/><div><strong>{{ t('status.error') }}</strong><p>{{ t('status.errorBody') }}</p></div></div>
    <template v-else-if="status">
      <div class="status-panel healthy"><div class="status-dot healthy"/><div><strong>{{ t('status.healthy') }}</strong></div></div>
      <dl class="details-list">
        <div><dt>{{ t('status.service') }}</dt><dd>{{ status.service }}</dd></div><div><dt>{{ t('status.version') }}</dt><dd>{{ status.version }}</dd></div>
        <div><dt>{{ t('status.upstream') }}</dt><dd>{{ status.upstream }}</dd></div><div><dt>{{ t('status.protocol') }}</dt><dd>{{ status.configuredProtocol }} ({{ status.upstreamProtocol }})</dd></div>
        <div><dt>{{ t('status.model') }}</dt><dd>{{ status.model || t('dashboard.notConfigured') }}</dd></div><div><dt>{{ t('status.debug') }}</dt><dd>{{ status.debugLoggingEnabled ? t('common.enabled') : t('common.disabled') }}</dd></div>
      </dl>
    </template>
  </section>
</template>
