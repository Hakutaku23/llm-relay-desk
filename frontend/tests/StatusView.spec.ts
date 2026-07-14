import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import StatusView from '@/views/StatusView.vue'
import { createAppI18n } from '@/i18n'

const health = { service:'LLM Relay Desk', version:'5.3.0', status:'ok', model:'mock/model', upstream:'http://127.0.0.1:18000/v1', upstream_protocol:'auto', resolved_upstream_protocol:'openai', debug_logging_enabled:true }
function render(locale: 'en-US'|'zh-CN'='en-US') { return mount(StatusView,{global:{plugins:[createAppI18n(locale)]}}) }

describe('system status',()=>{
  it('shows loading and success in English',async()=>{ let resolve!: (value:Response)=>void; vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>resolve=r))); const wrapper=render(); expect(wrapper.text()).toContain('Loading system status'); resolve(new Response(JSON.stringify(health))); await flushPromises(); expect(wrapper.text()).toContain('Relay service is operational'); expect(wrapper.text()).toContain('http://127.0.0.1:18000/v1'); expect(wrapper.text()).toContain('Enabled') })
  it('shows malformed data',async()=>{ vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{}'))); const wrapper=render(); await flushPromises(); expect(wrapper.text()).toContain('Malformed status response') })
  it('shows request failure',async()=>{ vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline'))); const wrapper=render(); await flushPromises(); expect(wrapper.text()).toContain('Status request failed') })
  it('renders Chinese',async()=>{ vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(health)))); const wrapper=render('zh-CN'); await flushPromises(); expect(wrapper.text()).toContain('中继服务运行正常'); expect(wrapper.text()).toContain('调试日志') })
})
