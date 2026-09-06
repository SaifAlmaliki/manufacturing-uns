import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'

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
  grafanaProxyTarget: string
  authRealm: string
  authBaseUrl: string
  authIssuer: string
  authClientId: string
}

const platformDir = dirname(fileURLToPath(import.meta.url))

function resolveSettingsPath(): string | undefined {
  const candidates = [
    process.env.UNS_CONF_DIR ? resolve(process.env.UNS_CONF_DIR, 'settings.yaml') : '',
    resolve(process.cwd(), '../conf/settings.yaml'),
    resolve(process.cwd(), 'conf/settings.yaml'),
    resolve(platformDir, '../../conf/settings.yaml'),
  ].filter(Boolean)
  return candidates.find((candidate) => existsSync(candidate))
}

export function platformSettingsFromConfig(
  defaults: Record<string, unknown> = {},
): PlatformSettings {
  const urls = (defaults.urls ?? {}) as Record<string, unknown>
  const platform = (defaults.platform ?? {}) as Record<string, unknown>
  const applications = (defaults.applications ?? {}) as Record<string, Record<string, unknown>>
  const frontend = applications.frontend ?? {}

  const graphqlHost = String(urls.graphql_host ?? 'localhost')
  const graphqlPort = Number(urls.graphql_port ?? 8000)
  const graphqlPath = String(urls.graphql_path ?? '/graphql')

  const auth = (defaults.auth ?? {}) as Record<string, unknown>
  const authRealm = String(auth.realm ?? 'uns')
  const authBaseUrl = String(auth.base_url ?? 'http://localhost:8088/auth')

  return {
    instanceName: String(platform.instance_name ?? 'default'),
    organizationName: String(platform.organization_name ?? ''),
    displayName: String(platform.display_name ?? 'Unified Namespace'),
    graphqlHost,
    graphqlPort,
    graphqlPath,
    graphqlUrl: `http://${graphqlHost}:${graphqlPort}${graphqlPath}`,
    graphqlProxyTarget: `http://${graphqlHost}:${graphqlPort}`,
    frontendDevPort: Number(frontend.dev_port ?? 5173),
    frontendComposePort: Number(frontend.compose_port ?? 8088),
    grafanaProxyTarget: String(urls.grafana_proxy_target ?? 'http://localhost:3000'),
    authRealm,
    authBaseUrl,
    // Absolute, not a relative path: OIDC discovery hands the browser absolute URLs and the
    // realm mints them from KC_HOSTNAME, so a dev session on 5173 uses this same authority.
    authIssuer: String(auth.issuer ?? `${authBaseUrl}/realms/${authRealm}`),
    authClientId: String(auth.console_client_id ?? 'uns-console'),
  }
}

export function loadPlatformSettings(): PlatformSettings {
  const settingsPath = resolveSettingsPath()
  if (!settingsPath) {
    return platformSettingsFromConfig()
  }
  const raw = parse(readFileSync(settingsPath, 'utf8')) as { default?: Record<string, unknown> }
  return platformSettingsFromConfig(raw.default ?? {})
}
