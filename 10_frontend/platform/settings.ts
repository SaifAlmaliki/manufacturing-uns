import { readFileSync } from 'node:fs'
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
}

const platformDir = dirname(fileURLToPath(import.meta.url))

function resolveSettingsPath(): string {
  const candidates = [
    process.env.UNS_CONF_DIR ? resolve(process.env.UNS_CONF_DIR, 'settings.yaml') : '',
    resolve(process.cwd(), '../conf/settings.yaml'),
    resolve(process.cwd(), 'conf/settings.yaml'),
    resolve(platformDir, '../../conf/settings.yaml'),
  ].filter(Boolean)
  for (const candidate of candidates) {
    try {
      readFileSync(candidate)
      return candidate
    } catch {
      // try next
    }
  }
  return resolve(process.cwd(), '../conf/settings.yaml')
}

export function loadPlatformSettings(): PlatformSettings {
  const raw = parse(readFileSync(resolveSettingsPath(), 'utf8')) as {
    default: Record<string, unknown>
  }
  const defaults = raw.default
  const urls = (defaults.urls ?? {}) as Record<string, unknown>
  const platform = (defaults.platform ?? {}) as Record<string, unknown>
  const applications = (defaults.applications ?? {}) as Record<string, Record<string, unknown>>
  const frontend = applications.frontend ?? {}

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
  }
}
