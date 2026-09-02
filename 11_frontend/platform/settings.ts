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
  simulatorApiPort: number
  simulatorProxyTarget: string
  grafanaProxyTarget: string
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
  const simulator = applications.simulator ?? {}
  const simulatorHost = String(urls.simulator_host ?? 'localhost')
  const simulatorApiPort = Number(simulator.api_port ?? 8099)

  const graphqlHost = String(urls.graphql_host ?? 'localhost')
  const graphqlPort = Number(urls.graphql_port ?? 8000)
  const graphqlPath = String(urls.graphql_path ?? '/graphql')

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
    simulatorApiPort,
    simulatorProxyTarget: `http://${simulatorHost}:${simulatorApiPort}`,
    grafanaProxyTarget: String(urls.grafana_proxy_target ?? 'http://localhost:3000'),
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
