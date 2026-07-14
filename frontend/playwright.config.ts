import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:11434',
    channel: 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: [
    { command: 'conda run -n ollama python app.py', cwd: '..', url: 'http://127.0.0.1:11434/health', reuseExistingServer: false, timeout: 30_000 },
    { command: 'conda run -n ollama python -m tools.mock_upstream --host 127.0.0.1 --port 18000', cwd: '..', url: 'http://127.0.0.1:18000/v1/models', reuseExistingServer: false, timeout: 30_000 },
  ],
})
