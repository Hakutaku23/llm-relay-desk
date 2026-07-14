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
