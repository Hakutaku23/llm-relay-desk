export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number]

export const LOCALE_STORAGE_KEY = 'llm-relay-desk.locale'

interface LocaleStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === 'string' && SUPPORTED_LOCALES.includes(value as SupportedLocale)
}

export function localeFromBrowser(language: string): SupportedLocale {
  return language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

export function resolveInitialLocale(
  storage: LocaleStorage = globalThis.localStorage,
  browserLanguage: string = globalThis.navigator.language,
): SupportedLocale {
  try {
    const stored = storage.getItem(LOCALE_STORAGE_KEY)
    if (isSupportedLocale(stored)) return stored
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
  return localeFromBrowser(browserLanguage)
}

export function persistLocale(locale: SupportedLocale, storage: LocaleStorage = globalThis.localStorage) {
  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // The active locale still changes when storage is unavailable.
  }
}
