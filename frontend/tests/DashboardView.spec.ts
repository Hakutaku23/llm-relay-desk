import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardView from '@/views/DashboardView.vue'
import { createAppI18n } from '@/i18n'
import type { SupportedLocale } from '@/i18n/locale'

const validHealth = {
  service: 'LLM Relay Desk',
  version: '5.3.0',
  status: 'ok',
  model: 'local-model',
  resolved_upstream_protocol: 'openai',
  upstream: 'private-value-that-must-not-be-stored',
}

function deferredResponse() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function mountDashboard(locale: SupportedLocale = 'en-US') {
  return mount(DashboardView, { global: { plugins: [createAppI18n(locale)] } })
}

describe('DashboardView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('shows the health loading state', () => {
    const pending = deferredResponse()
    vi.stubGlobal('fetch', vi.fn(() => pending.promise))
    const wrapper = mountDashboard()
    expect(wrapper.text()).toContain('Checking relay')
  })

  it.each([
    ['en-US', 'Relay healthy'],
    ['zh-CN', '中继运行正常'],
  ] as const)('renders a successful health summary in %s', async (locale, healthyText) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(validHealth))))
    const wrapper = mountDashboard(locale)
    await flushPromises()
    expect(wrapper.text()).toContain(healthyText)
    expect(wrapper.text()).toContain('LLM Relay Desk 5.3.0')
    expect(wrapper.text()).toContain('local-model')
    expect(wrapper.text()).toContain('openai')
    expect(wrapper.text()).not.toContain(validHealth.upstream)
  })

  it.each([
    ['en-US', 'Health request failed', 'The local relay could not be reached.'],
    ['zh-CN', '健康检查请求失败', '无法连接到本地中继服务。'],
  ] as const)('renders a request failure in %s', async (locale, title, body) => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network unavailable')))
    const wrapper = mountDashboard(locale)
    await flushPromises()
    expect(wrapper.text()).toContain(title)
    expect(wrapper.text()).toContain(body)
    expect(wrapper.text()).not.toContain('Network unavailable')
  })

  it.each([
    ['en-US', 'Malformed health response', 'The relay returned an invalid health response.'],
    ['zh-CN', '健康响应格式错误', '中继返回了无效的健康状态响应。'],
  ] as const)('renders a malformed-response state in %s', async (locale, title, body) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }))))
    const wrapper = mountDashboard(locale)
    await flushPromises()
    expect(wrapper.text()).toContain(title)
    expect(wrapper.text()).toContain(body)
  })
})
