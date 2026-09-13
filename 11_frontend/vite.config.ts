import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig, type Plugin } from 'vite'
import { loadPlatformSettings, type PlatformSettings } from './platform/settings.ts'

const platform = loadPlatformSettings()

function brandHtmlPlugin(settings: PlatformSettings): Plugin {
  return {
    name: 'brand-html',
    transformIndexHtml(html) {
      return html
        .replaceAll('%CONSOLE_NAME%', settings.consoleName)
        .replaceAll('%PRODUCT_NAME%', settings.productName)
    },
  }
}

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss(), brandHtmlPlugin(platform)],
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
        '/grafana': {
          target: platform.grafanaProxyTarget,
          changeOrigin: true,
          ws: true,
        },
        '/agent': {
          target: platform.agentProxyTarget,
          changeOrigin: true,
        },
      },
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  }
})
