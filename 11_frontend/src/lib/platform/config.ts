export type PlatformSettings = {
  instanceName: string
  organizationName: string
  displayName: string
  graphqlHost: string
  graphqlPort: number
  graphqlPath: string
  graphqlUrl: string
  graphqlProxyTarget: string
  frontendDevPort: number
  frontendComposePort: number
  simulatorApiPort: number
  simulatorProxyTarget: string
  grafanaProxyTarget: string
  authRealm: string
  authBaseUrl: string
  authIssuer: string
  authClientId: string
}

declare const __UNS_PLATFORM_CONFIG__: PlatformSettings

export const platformConfig: PlatformSettings = __UNS_PLATFORM_CONFIG__
