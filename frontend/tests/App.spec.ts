import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import App from '@/App.vue'
import { createAppI18n } from '@/i18n'
import { LOCALE_STORAGE_KEY, type SupportedLocale } from '@/i18n/locale'
import { routes } from '@/router'

async function mountAt(path: string, locale: SupportedLocale = 'en-US') {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          service: 'LLM Relay Desk',
          version: '5.3.0',
          status: 'ok',
          model: null,
          resolved_upstream_protocol: 'ollama',
          upstream: 'http://127.0.0.1:18000/v1',
          upstream_protocol: 'auto',
          debug_logging_enabled: false,
        }),
      ),
    ),
  )
  const router = createRouter({ history: createMemoryHistory('/ui/'), routes })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    global: { plugins: [createPinia(), router, createAppI18n(locale)] },
  })
  await flushPromises()
  return wrapper
}

describe('router shell', () => {
  it('renders the application shell and dashboard route', async () => {
    const wrapper = await mountAt('/')
    expect(wrapper.text()).toContain('LLM Relay Desk')
    expect(wrapper.text()).toContain('Relay operations')
    expect(wrapper.text()).toContain('Dashboard')
    expect(document.title).toBe('Dashboard - LLM Relay Desk')
  })

  it.each([
    ['en-US', 'Relay operations', 'Page not found', 'Page not found - LLM Relay Desk'],
    ['zh-CN', '中继运行状态', '页面不存在', '页面不存在 - LLM Relay Desk'],
  ] as const)('renders the not-found route in %s', async (locale, header, title, documentTitle) => {
    const wrapper = await mountAt('/missing-view', locale)
    expect(wrapper.text()).toContain(header)
    expect(wrapper.text()).toContain(title)
    expect(document.title).toBe(documentTitle)
  })

  it('switches language, persists it, and updates the HTML language', async () => {
    localStorage.clear()
    const wrapper = await mountAt('/', 'en-US')
    expect(document.documentElement.lang).toBe('en-US')
    await wrapper.get('select[aria-label="Language"]').setValue('zh-CN')
    await flushPromises()
    expect(wrapper.text()).toContain('中继运行状态')
    expect(wrapper.text()).toContain('仪表盘')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.title).toBe('仪表盘 - LLM Relay Desk')
  })

  it('exposes only implemented navigation targets', async () => {
    const wrapper = await mountAt('/')
    const links = wrapper.findAll('nav a')
    expect(links.map((link) => link.attributes('href'))).toEqual([
      '/ui/',
      '/ui/status',
      '/ui/settings',
      '/ui/api-test',
      '/ui/prompts',
      '/ui/task-isolation',
      '/ui/subtitles',
      '/ui-legacy/',
      '/monitor/',
    ])
    expect(wrapper.text()).toContain('Legacy Management UI')
    expect(wrapper.text()).toContain('Realtime Monitor')
  })
})
