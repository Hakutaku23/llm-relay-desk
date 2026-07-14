import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/ui/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/health': 'http://127.0.0.1:11434',
      '/admin': 'http://127.0.0.1:11434',
      '/ui-legacy': 'http://127.0.0.1:11434',
      '/monitor': 'http://127.0.0.1:11434',
      '/ws/monitor': {
        target: 'ws://127.0.0.1:11434',
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
  },
})
