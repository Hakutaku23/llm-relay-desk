import { createI18n } from 'vue-i18n'

import enUS from '@/locales/en-US'
import zhCN from '@/locales/zh-CN'

import { resolveInitialLocale, type SupportedLocale } from './locale'

export function createAppI18n(locale: SupportedLocale = resolveInitialLocale()) {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en-US',
    messages: {
      'zh-CN': zhCN,
      'en-US': enUS,
    },
  })
}

export const i18n = createAppI18n()
