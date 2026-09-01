/// <reference types="vite/client" />

declare const __UNS_PLATFORM_CONFIG__: import('../../platform/settings').PlatformSettings

interface ImportMetaEnv {
  readonly VITE_GRAPHQL_URL?: string
  readonly VITE_GRAPHQL_WS_URL?: string
  /** Sent as X-Simulator-Token. Unset means the simulator's API takes no token. */
  readonly VITE_SIMULATOR_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.jpg' {
  const src: string;
  export default src;
}

declare module '*.jpeg' {
  const src: string;
  export default src;
}

declare module '*.png' {
  const src: string;
  export default src;
}

declare module '*.svg' {
  const src: string;
  export default src;
}

declare module '*.webp' {
  const src: string;
  export default src;
}
