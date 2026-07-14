import { expect, test } from '@playwright/test'

test('Vue, legacy, and monitor routes remain local and reachable', async ({ page }) => {
  const upstreamRequests: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) upstreamRequests.push(request.url())
  })
  await page.addInitScript(() => localStorage.setItem('llm-relay-desk.locale', 'en-US'))

  await page.goto('/ui/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('Relay healthy')).toBeVisible()

  await page.goto('/ui/missing-view')
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()

  await page.goto('/ui-legacy/')
  await expect(page.locator('h1')).toContainText('LLM Relay Desk')

  await page.goto('/monitor/')
  await expect(page.locator('h1')).toBeVisible()
  expect(upstreamRequests).toEqual([])
})

test('status and settings use local APIs without persisting secrets', async ({ page }) => {
  const externalRequests: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.push(request.url())
  })
  await page.addInitScript(() => localStorage.setItem('llm-relay-desk.locale', 'en-US'))
  const config = {
    upstream_base_url: 'http://127.0.0.1:18000/v1', upstream_protocol: 'openai',
    default_model: 'mock/openai-nonstream-usage', request_timeout_seconds: 600,
    native_popup_force_upstream_stream: true, force_reasoning_enabled: false,
    default_reasoning_effort: '', prompt_enabled: true, debug_logging_enabled: false,
    debug_log_directory: 'debug_logs', debug_log_retention_files: 100,
    upstream_api_key: '', local_api_key: '',
  }
  const secretStatus = {
    format_version: 1,
    upstream_api_key: { configured: true, source: 'encrypted_file', environment_variable: 'UPSTREAM_API_KEY', webui_writable: true },
    local_api_key: { configured: true, source: 'encrypted_file', environment_variable: 'LOCAL_API_KEY', webui_writable: true },
  }
  await page.route('**/admin/config', async (route) => {
    if (route.request().method() === 'PUT') {
      const submitted = route.request().postDataJSON()
      await route.fulfill({ json: { ok: true, config: { ...config, default_model: submitted.default_model } } })
    } else await route.fulfill({ json: config })
  })
  await page.route('**/admin/secrets/status', (route) => route.fulfill({ json: secretStatus }))

  await page.goto('/ui/status')
  await expect(page.getByRole('heading', { name: 'System Status' })).toBeVisible()
  await expect(page.getByText('Relay service is operational')).toBeVisible()

  await page.goto('/ui/settings')
  await expect(page.getByRole('heading', { name: 'Relay Settings' })).toBeVisible()
  const model = page.getByLabel('Default model')
  await model.fill('mock/changed-model')
  await page.getByRole('button', { name: 'Save configuration' }).click()
  await expect(page.getByText('Configuration saved.')).toBeVisible()
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))
  expect(JSON.stringify(storage)).not.toContain('sk-')
  expect(JSON.stringify(storage)).not.toContain('API_KEY')
  expect(externalRequests).toEqual([])
})

test('API test uses the deterministic loopback mock for models and chat', async ({ page, request }) => {
  const externalRequests: string[] = []
  page.on('request', (value) => {
    const host = new URL(value.url()).hostname
    if (!['127.0.0.1', 'localhost'].includes(host)) externalRequests.push(value.url())
  })
  await page.addInitScript(() => localStorage.setItem('llm-relay-desk.locale', 'en-US'))
  const config = {
    upstream_base_url: 'http://127.0.0.1:18000/v1', upstream_protocol: 'openai',
    default_model: 'mock/openai-nonstream-usage', request_timeout_seconds: 600,
    native_popup_force_upstream_stream: true, force_reasoning_enabled: false,
    default_reasoning_effort: '', prompt_enabled: true, prompt_injection_mode: 'normal',
    debug_logging_enabled: false, debug_log_directory: 'debug_logs', debug_log_retention_files: 100,
  }
  let scenario = 'openai-nonstream-usage'
  await page.route('**/admin/config', (route) => route.fulfill({ json: config }))
  await page.route('**/admin/test-upstream', async (route) => {
    const mock = await request.get('http://127.0.0.1:18000/v1/models')
    await route.fulfill({ json: { ok: true, resolved_protocol: 'openai', elapsed_ms: 1, response: await mock.json() } })
  })
  await page.route('**/admin/test-chat', async (route) => {
    const mock = await request.post('http://127.0.0.1:18000/v1/chat/completions', {
      headers: { 'X-Mock-Scenario': scenario }, data: route.request().postDataJSON(),
    })
    const headers = mock.headers()
    delete headers['content-length']
    delete headers['content-encoding']
    await route.fulfill({ status: mock.status(), headers, body: await mock.body() })
  })
  await page.goto('/ui/api-test')
  await expect(page.getByRole('heading', { name: 'API Test' })).toBeVisible()
  await page.getByRole('button', { name: 'Check connectivity' }).click()
  await expect(page.getByText(/16 models/)).toBeVisible()

  await page.getByLabel('Streaming response').uncheck()
  await page.getByRole('button', { name: 'Send test' }).click()
  await expect(page.getByText('Mock OpenAI response.', { exact: true })).toBeVisible()

  scenario = 'openai-stream-final-usage'
  await page.getByLabel('Streaming response').check()
  await page.getByRole('button', { name: 'Send test' }).click()
  await expect(page.getByText('Mock stream.', { exact: true })).toBeVisible()

  scenario = 'reasoning-only'
  await page.getByLabel('Streaming response').uncheck()
  await page.getByRole('button', { name: 'Send test' }).click()
  await expect(page.getByText('Mock reasoning only.', { exact: true })).toBeVisible()
  await expect(page.getByText('No content returned')).toBeVisible()

  scenario = 'http-429'
  await page.getByRole('button', { name: 'Send test' }).click()
  await expect(page.getByText(/429: Mock rate limit exceeded/)).toBeVisible()
  expect(externalRequests).toEqual([])
})

test('prompt profiles and task isolation use temporary backend data', async ({ page }) => {
  const externalRequests: string[] = []
  page.on('request', (request) => {
    const host = new URL(request.url()).hostname
    if (!['127.0.0.1', 'localhost'].includes(host)) externalRequests.push(request.url())
  })
  await page.addInitScript(() => localStorage.setItem('llm-relay-desk.locale', 'en-US'))
  let active: string | null = 'Default'
  const profiles: Record<string, string> = { Default: 'Default prompt' }
  const promptBody = () => ({ active, names: Object.keys(profiles), profiles })
  await page.route('**/admin/prompts/**', async (route) => {
    const url = new URL(route.request().url())
    const parts = url.pathname.split('/').filter(Boolean)
    const activate = parts.at(-1) === 'activate'
    const name = decodeURIComponent(parts[activate ? parts.length - 2 : parts.length - 1] ?? '')
    if (route.request().method() === 'PUT') {
      profiles[name] = route.request().postDataJSON().content
      await route.fulfill({ json: { ok: true, name, active } })
    } else if (route.request().method() === 'DELETE') {
      delete profiles[name]
      if (active === name) active = Object.keys(profiles)[0] ?? null
      await route.fulfill({ json: { ok: true, active } })
    } else {
      active = name
      await route.fulfill({ json: { ok: true, active } })
    }
  })
  await page.route('**/admin/prompts', (route) => route.fulfill({ json: promptBody() }))
  let taskConfig = {
    prompt_enabled: true, prompt_injection_mode: 'normal', player_friendly_injection_enabled: true,
    enable_player_initiated_dialogue: true, enable_action_dialogue: false,
    enable_npc_initiated_dialogue: true,
  }
  await page.route('**/admin/config', async (route) => {
    if (route.request().method() === 'PUT') taskConfig = { ...taskConfig, ...route.request().postDataJSON() }
    await route.fulfill({ json: route.request().method() === 'PUT' ? { ok: true, config: taskConfig } : taskConfig })
  })

  await page.goto('/ui/prompts')
  await expect(page.getByRole('heading', { name: 'Prompt Profiles' })).toBeVisible()
  await page.getByRole('button', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill('Created')
  await page.getByLabel('System prompt content').fill('Created content')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByText('Profile saved.')).toBeVisible()
  await page.getByLabel('System prompt content').fill('Edited content')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await page.getByRole('button', { name: 'Set active' }).click()
  await expect(page.getByText('Active profile updated.')).toBeVisible()

  await page.locator('input[type=file]').setInputFiles({
    name: 'profiles.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ format_version: 1, active: 'Imported', profiles: [{ id: 'Imported', name: 'Imported', content: 'Imported content' }] })),
  })
  await expect(page.getByText('Profiles imported.')).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export all' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('llm-relay-desk-prompts.json')

  await page.goto('/ui/task-isolation')
  await expect(page.getByRole('heading', { name: 'Task Isolation' })).toBeVisible()
  await page.getByLabel('Injection mode').selectOption('bannerlord')
  await page.getByLabel('Player trade, command, and request').check()
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Task-isolation settings saved.')).toBeVisible()
  expect(externalRequests).toEqual([])
})

test('subtitle settings use temporary data and a mocked desktop positioning response', async ({ page }) => {
  const externalRequests:string[]=[];page.on('request',r=>{if(!['127.0.0.1','localhost'].includes(new URL(r.url()).hostname))externalRequests.push(r.url())});await page.addInitScript(()=>localStorage.setItem('llm-relay-desk.locale','en-US'))
  const config={native_popup_enabled:true,native_popup_close_seconds:30,native_popup_position:'bottom_center',native_popup_offset_x:0,native_popup_offset_y:0,native_popup_custom_x:120,native_popup_custom_y:120,native_popup_width:960,native_popup_height:220,native_popup_font_size:24,native_popup_font_family:'Segoe UI',native_popup_text_align:'left',native_popup_text_opacity:1,native_popup_background_opacity:.88,native_popup_content_mode:'dialogue',native_popup_dialogue_fields:['response'],native_popup_plain_text_fallback:true,native_popup_force_upstream_stream:true,native_popup_show_reasoning:false,native_popup_click_through:false,native_popup_text_shadow:true,native_popup_shadow_color:'#000000',native_popup_shadow_offset:2,native_popup_text_outline:false,native_popup_outline_color:'#000000',native_popup_outline_width:0,native_popup_background_color:'#101318',native_popup_text_color:'#f7f8fa',native_popup_muted_color:'#aeb6c2',native_popup_border_color:'#343a46',native_popup_error_color:'#ff8f9b'}
  await page.route('**/admin/subtitle-config',async route=>{if(route.request().method()==='PUT')Object.assign(config,route.request().postDataJSON());await route.fulfill({json:route.request().method()==='PUT'?{ok:true,config}:config})});await page.route('**/admin/subtitle-fonts',r=>r.fulfill({json:{fonts:['Segoe UI','Consolas'],platform:'win32'}}));await page.route('**/admin/subtitle-preview.png',r=>r.fulfill({contentType:'image/png',body:Buffer.from('89504e470d0a1a0a','hex')}));await page.route('**/admin/subtitle-positioning/start',r=>r.fulfill({json:{ok:true,request_id:'preview_e2e',positioning:true}}))
  await page.goto('/ui/subtitles');await expect(page.getByRole('heading',{name:'Subtitle Settings'})).toBeVisible();await page.getByLabel('Font family').fill('Consolas');await page.getByLabel('Background opacity').fill('0.42');await page.getByLabel('Show reasoning text').check();await page.getByRole('button',{name:'Generate preview'}).click();await page.getByRole('button',{name:'Save settings'}).click();await expect(page.getByText('Subtitle settings saved.')).toBeVisible();await page.getByRole('button',{name:'Enter positioning mode'}).click();await expect(page.getByRole('status')).toContainText('60 seconds');expect(config.native_popup_font_family).toBe('Consolas');expect(config.native_popup_background_opacity).toBe(.42);expect(externalRequests).toEqual([])
})
