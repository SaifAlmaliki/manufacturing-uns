import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vite'
import { loadPlatformSettings } from './platform/settings.ts'

const platform = loadPlatformSettings()

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    define: {
      __UNS_PLATFORM_CONFIG__: platform,
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: platform.frontendDevPort,
      proxy: {
        '/graphql': {
          target: platform.graphqlProxyTarget,
          changeOrigin: true,
          ws: true,
        },
        // The simulator's control API. No `ws: true`: the console polls it over HTTP and
        // gets its live feed from MQTT through /graphql.
        '/simulator': {
          target: platform.simulatorProxyTarget,
          changeOrigin: true,
        },
        '/grafana': {
          target: platform.grafanaProxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  }
})
