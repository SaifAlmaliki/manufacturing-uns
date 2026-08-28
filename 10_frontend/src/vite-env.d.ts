/// <reference types="vite/client" />

declare const __UNS_PLATFORM_CONFIG__: string

interface ImportMetaEnv {
  readonly VITE_GRAPHQL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
