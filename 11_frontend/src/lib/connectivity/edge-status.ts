/**
 * Edge reconciliation and heartbeat presentation for the connectivity console.
 * Keeps desired/applied lifecycle separate from per-connection probe health.
 */

import type { GraphqlConnectivityServer, GraphqlEdgeDevice } from '../../services/graphql/types'

export const EDGE_APPLIED_PHASES = [
  'waiting_for_routes',
  'pending',
  'applying',
  'applied',
  'failed',
  'degraded',
] as const

export type EdgeAppliedPhase = (typeof EDGE_APPLIED_PHASES)[number]

/** Default heartbeat staleness — edges report about every 30s in production. */
export const EDGE_HEARTBEAT_STALE_MS = 120_000

export function isCloudEdgeMode(edges: GraphqlEdgeDevice[]): boolean {
  return edges.length > 0
}

export function edgeProtocols(
  capabilities: Record<string, unknown> | null | undefined,
): string[] {
  const raw = capabilities?.protocols
  if (!Array.isArray(raw)) return []
  return raw.map((value) => String(value).toLowerCase())
}

export function edgeSupportsProtocol(
  capabilities: Record<string, unknown> | null | undefined,
  protocol: string,
): boolean {
  const normalized = protocol.toLowerCase().replace(/_/g, '_')
  const aliases: Record<string, string[]> = {
    opc_ua: ['opc_ua'],
    modbus_tcp: ['modbus'],
    modbus: ['modbus'],
    s7: ['s7'],
    ethernet_ip: ['ethernet_ip'],
  }
  const wanted = aliases[normalized] ?? [normalized]
  const supported = edgeProtocols(capabilities)
  return wanted.some((name) => supported.includes(name))
}

export function discoverySupported(
  capabilities: Record<string, unknown> | null | undefined,
  protocol: string,
): boolean {
  if (!edgeSupportsProtocol(capabilities, protocol)) return false
  const discovery = capabilities?.discovery
  if (discovery && typeof discovery === 'object' && !Array.isArray(discovery)) {
    const flag = (discovery as Record<string, unknown>)[protocol.replace(/_tcp$/, '')]
    if (flag === false) return false
  }
  return protocol === 'opc_ua' || protocol === 'OPC_UA'
}

export function isEdgeHeartbeatStale(
  lastSeen: string | null | undefined,
  nowMs = Date.now(),
  staleMs = EDGE_HEARTBEAT_STALE_MS,
): boolean {
  if (!lastSeen) return true
  const seen = Date.parse(lastSeen)
  if (Number.isNaN(seen)) return true
  return nowMs - seen > staleMs
}

export function edgeConnectionState(
  device: Pick<GraphqlEdgeDevice, 'status' | 'lastSeen'>,
  nowMs = Date.now(),
): 'online' | 'offline' | 'revoked' {
  if (device.status === 'revoked') return 'revoked'
  if (isEdgeHeartbeatStale(device.lastSeen, nowMs)) return 'offline'
  return 'online'
}

export function revisionLagLabel(desired: number, applied: number): string {
  if (applied >= desired) return 'In sync'
  const lag = desired - applied
  return lag === 1 ? '1 revision behind' : `${lag} revisions behind`
}

export function normalizeAppliedPhase(phase: string | null | undefined): EdgeAppliedPhase | 'unknown' {
  const value = (phase ?? '').toLowerCase()
  if ((EDGE_APPLIED_PHASES as readonly string[]).includes(value)) {
    return value as EdgeAppliedPhase
  }
  return value ? 'unknown' : 'pending'
}

const PHASE_DOT: Record<string, string> = {
  waiting_for_routes: 'bg-amber-400',
  pending: 'bg-amber-500',
  applying: 'bg-sky-500',
  applied: 'bg-emerald-500',
  failed: 'bg-rose-500',
  degraded: 'bg-orange-500',
  unknown: 'bg-zinc-500',
}

const PHASE_LABEL: Record<string, string> = {
  waiting_for_routes: 'Waiting for routes',
  pending: 'Pending',
  applying: 'Applying',
  applied: 'Applied',
  failed: 'Failed',
  degraded: 'Degraded',
  unknown: 'Unknown',
}

export function edgePhaseDotClass(phase: string | null | undefined): string {
  return PHASE_DOT[normalizeAppliedPhase(phase)] ?? PHASE_DOT.unknown
}

export function edgePhaseLabel(phase: string | null | undefined): string {
  return PHASE_LABEL[normalizeAppliedPhase(phase)] ?? 'Pending'
}

const HEALTH_DOT: Record<string, string> = {
  connected: 'bg-emerald-500',
  pending: 'bg-amber-500',
  failed: 'bg-rose-500',
  untested: 'bg-zinc-500',
  degraded: 'bg-orange-500',
}

const HEALTH_LABEL: Record<string, string> = {
  connected: 'Connected',
  pending: 'Pending',
  failed: 'Failed',
  untested: 'Untested',
  degraded: 'Degraded',
}

export function connectionHealthDotClass(health: string | null | undefined): string {
  const key = (health ?? 'untested').toLowerCase()
  return HEALTH_DOT[key] ?? HEALTH_DOT.untested
}

export function connectionHealthLabel(health: string | null | undefined): string {
  const key = (health ?? 'untested').toLowerCase()
  return HEALTH_LABEL[key] ?? 'Untested'
}

export function serverConnectionHealth(server: GraphqlConnectivityServer): string {
  return server.connectionHealth ?? server.lastStatus ?? 'untested'
}

export function saveDoesNotImplyConnected(cloudMode: boolean): string | null {
  if (!cloudMode) return null
  return 'Saved to desired state — connection success requires an explicit Test after the edge applies.'
}
