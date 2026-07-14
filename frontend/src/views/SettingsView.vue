<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { clearSecret, getConfig, getSecretStatus, revealLocalKey, saveConfig } from '@/api/admin'
import SecretControl from '@/components/SecretControl.vue'
import type { RelayConfig, SecretName, SecretStatus } from '@/types/admin'

const { t } = useI18n()
const config = ref<RelayConfig | null>(null), baseline = ref(''), state = ref<'loading'|'ready'|'error'>('loading'), saving = ref(false)
const error = ref(''), success = ref(''), revealed = ref(''), secrets = reactive<Record<SecretName,string>>({ upstream_api_key: '', local_api_key: '' })
const secretStatus = ref<SecretStatus | null>(null)
const dirty = computed(() => !!config.value && (JSON.stringify(config.value) !== baseline.value || !!secrets.upstream_api_key || !!secrets.local_api_key))
const fieldErrors = computed(() => ({ upstream: config.value && !/^https?:\/\//i.test(config.value.upstreamBaseUrl) ? t('settings.errors.upstream') : '', model: config.value && !config.value.defaultModel.trim() ? t('settings.errors.model') : '', timeout: config.value && (config.value.requestTimeoutSeconds < 30 || config.value.requestTimeoutSeconds > 7200) ? t('settings.errors.timeout') : '', retention: config.value && (config.value.debugLogRetentionFiles < 1 || config.value.debugLogRetentionFiles > 10000) ? t('settings.errors.retention') : '' }))
const valid = computed(() => Object.values(fieldErrors.value).every((item) => !item))
async function load() { state.value='loading'; error.value=''; try { const [loaded,status]=await Promise.all([getConfig(),getSecretStatus()]); config.value=loaded; baseline.value=JSON.stringify(loaded); secretStatus.value=status; state.value='ready' } catch(e) { error.value=e instanceof Error?e.message:''; state.value='error' } }
async function submit() { if (!config.value || !valid.value || saving.value) return; saving.value=true; error.value=''; success.value=''; try { const saved=await saveConfig(config.value,secrets); config.value=saved; baseline.value=JSON.stringify(saved); secrets.upstream_api_key=''; secrets.local_api_key=''; secretStatus.value=await getSecretStatus(); success.value=t('settings.saved') } catch(e) { error.value=e instanceof Error?e.message:t('settings.saveError') } finally { saving.value=false } }
async function reveal() { try { revealed.value=await revealLocalKey() } catch(e) { error.value=e instanceof Error?e.message:'' } }
async function clear(name: SecretName) { if (!globalThis.confirm(t('secrets.confirmClear'))) return; try { secretStatus.value=await clearSecret(name); if(name==='local_api_key') revealed.value='' } catch(e) { error.value=e instanceof Error?e.message:'' } }
function beforeUnload(event: unknown) { if(dirty.value){ const unloadEvent=event as { preventDefault:()=>void; returnValue:boolean }; unloadEvent.preventDefault(); unloadEvent.returnValue=false } }
onBeforeRouteLeave(() => !dirty.value || globalThis.confirm(t('settings.unsavedConfirm')))
onMounted(() => { globalThis.window.addEventListener('beforeunload', beforeUnload); load() })
onBeforeUnmount(() => { globalThis.window.removeEventListener('beforeunload', beforeUnload); revealed.value=''; secrets.upstream_api_key=''; secrets.local_api_key='' })
</script>
<template><section class="page settings-page"><header class="page-heading"><div><p class="eyebrow">{{ t('settings.eyebrow') }}</p><h1>{{ t('settings.title') }}</h1></div></header>
  <div v-if="state==='loading'" class="status-panel"><div class="status-dot"/><strong>{{ t('settings.loading') }}</strong></div><div v-else-if="state==='error'" class="status-panel error"><div class="status-dot error"/><div><strong>{{ t('settings.loadError') }}</strong><p>{{ error }}</p><button @click="load">{{ t('common.retry') }}</button></div></div>
  <form v-else-if="config && secretStatus" @submit.prevent="submit">
    <section class="form-section"><h2>{{ t('settings.relay') }}</h2><div class="form-grid">
      <label>{{ t('settings.upstream') }}<input v-model.trim="config.upstreamBaseUrl"><small class="field-error">{{ fieldErrors.upstream }}</small></label>
      <label>{{ t('settings.protocol') }}<select v-model="config.upstreamProtocol"><option v-for="p in ['auto','openai','ollama','vllm']" :key="p" :value="p">{{ t(`settings.protocols.${p}`) }}</option></select></label>
      <label>{{ t('settings.model') }}<input v-model.trim="config.defaultModel"><small class="field-error">{{ fieldErrors.model }}</small></label>
      <label>{{ t('settings.timeout') }}<input v-model.number="config.requestTimeoutSeconds" type="number" min="30" max="7200"><small class="field-error">{{ fieldErrors.timeout }}</small></label>
      <label class="check"><input v-model="config.forceUpstreamStream" type="checkbox">{{ t('settings.forceStream') }}</label><label class="check"><input v-model="config.forceReasoningEnabled" type="checkbox">{{ t('settings.forceReasoning') }}</label>
      <label>{{ t('settings.effort') }}<select v-model="config.defaultReasoningEffort"><option v-for="e in ['','none','low','medium','high','max']" :key="e" :value="e">{{ e ? t(`settings.efforts.${e}`) : t('settings.modelDefault') }}</option></select></label>
      <label class="check"><input v-model="config.promptEnabled" type="checkbox">{{ t('settings.promptInjection') }}</label><label class="check"><input v-model="config.debugLoggingEnabled" type="checkbox">{{ t('settings.debug') }}</label>
      <label>{{ t('settings.debugDirectory') }}<input v-model.trim="config.debugLogDirectory"></label><label>{{ t('settings.retention') }}<input v-model.number="config.debugLogRetentionFiles" type="number" min="1" max="10000"><small class="field-error">{{ fieldErrors.retention }}</small></label>
    </div></section>
    <section class="form-section"><h2>{{ t('secrets.title') }}</h2><SecretControl :name="t('secrets.upstream')" :info="secretStatus.upstream_api_key" :value="secrets.upstream_api_key" :busy="saving" @update:value="secrets.upstream_api_key=$event" @clear="clear('upstream_api_key')"/><SecretControl :name="t('secrets.local')" :info="secretStatus.local_api_key" :value="secrets.local_api_key" :revealed="revealed" allow-reveal :busy="saving" @update:value="secrets.local_api_key=$event" @reveal="reveal" @clear="clear('local_api_key')"/></section>
    <p v-if="error" class="form-message error-text">{{ error }}</p><p v-if="success" class="form-message success-text">{{ success }}</p><button class="primary-button" type="submit" :disabled="saving || !dirty || !valid">{{ saving?t('settings.saving'):t('settings.save') }}</button>
  </form></section></template>
