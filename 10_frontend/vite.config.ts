import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { loadPlatformSettings } from './platform/settings.ts'

const platform = loadPlatformSettings()

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __UNS_PLATFORM_CONFIG__: platform,
  },
  server: {
    port: platform.frontendDevPort,
    proxy: {
      '/graphql': {
        target: platform.graphqlProxyTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    pool: 'forks',
    maxWorkers: 1,
    fileParallelism: false,
    testTimeout: 8000,
  },
})
