/// <reference types="vite/client" />

declare const __UNS_PLATFORM_CONFIG__: import('../../platform/settings').PlatformSettings

interface ImportMetaEnv {
  readonly VITE_GRAPHQL_URL?: string
  readonly VITEST?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
