import { describe, expect, it } from 'vitest'

import {
  LOCALE_STORAGE_KEY,
  localeFromBrowser,
  resolveInitialLocale,
} from '@/i18n/locale'

function storageWith(value: string | null) {
  return {
    getItem: (key: string) => (key === LOCALE_STORAGE_KEY ? value : null),
    setItem: () => undefined,
  }
}

describe('locale resolution', () => {
  it('uses English for the default non-Chinese browser locale', () => {
    expect(resolveInitialLocale(storageWith(null), 'en-US')).toBe('en-US')
  })

  it('gives a valid stored locale priority over the browser', () => {
    expect(resolveInitialLocale(storageWith('en-US'), 'zh-CN')).toBe('en-US')
    expect(resolveInitialLocale(storageWith('zh-CN'), 'en-US')).toBe('zh-CN')
  })

  it('maps Chinese browser locales to zh-CN', () => {
    expect(localeFromBrowser('zh-TW')).toBe('zh-CN')
    expect(resolveInitialLocale(storageWith('unsupported'), 'zh-Hans-CN')).toBe('zh-CN')
  })

  it('maps other browser locales to en-US', () => {
    expect(localeFromBrowser('fr-FR')).toBe('en-US')
    expect(resolveInitialLocale(storageWith(null), 'ja-JP')).toBe('en-US')
  })
})
