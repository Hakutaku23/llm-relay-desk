<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SecretInfo } from '@/types/admin'
const props = defineProps<{ name: string; info: SecretInfo; value: string; revealed?: string; allowReveal?: boolean; busy?: boolean }>()
const emit = defineEmits<{ 'update:value': [value: string]; reveal: []; clear: [] }>()
const { t } = useI18n()
const source = computed(() => t(`secrets.sources.${props.info.source}`))
</script>
<template>
  <fieldset class="secret-control"><legend>{{ name }}</legend>
    <div class="secret-meta"><span>{{ info.configured ? t('secrets.configured') : t('secrets.notConfigured') }}</span><span>{{ t('secrets.source') }}: {{ source }}</span><span>{{ info.webuiWritable ? t('secrets.writable') : t('secrets.readOnly') }}</span></div>
    <input type="password" autocomplete="new-password" :disabled="!info.webuiWritable || busy" :placeholder="info.configured ? t('secrets.preservePlaceholder') : t('secrets.enterPlaceholder')" :value="value" @input="emit('update:value', ($event.target as HTMLInputElement).value)">
    <div class="button-row"><button v-if="allowReveal" type="button" :disabled="busy || !info.configured" @click="emit('reveal')">{{ t('secrets.reveal') }}</button><button type="button" :disabled="busy || !info.webuiWritable || !info.configured" @click="emit('clear')">{{ t('secrets.clear') }}</button></div>
    <output v-if="revealed" class="revealed-secret">{{ revealed }}</output>
  </fieldset>
</template>
