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
