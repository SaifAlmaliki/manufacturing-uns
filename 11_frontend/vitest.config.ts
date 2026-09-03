import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vitest/config'
import { loadPlatformSettings } from './platform/settings.ts'

const platform = loadPlatformSettings()

export default defineConfig({
  plugins: [react()],
  // Same define as vite.config.ts: src/lib/platform/config.ts reads this at module scope,
  // so without it every test that transitively imports the client fails on an undefined global.
  define: {
    __UNS_PLATFORM_CONFIG__: platform,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
