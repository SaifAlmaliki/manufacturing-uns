import type { UnsNode } from '../../types/uns'

export type NodeRole = 'structural' | 'equipment' | 'parameter-group' | 'sensor' | 'other'

/**
 * Node types from two sources land here: the graph database labels topics by depth
 * ('DEVICE_depth_2'), while the Asset Model labels Assets by Asset Level ('WORK_CELL')
 * and the segments below them as Metrics. Both have to answer the same question —
 * what is this row in the tree — so both are mapped onto one role.
 */
const STRUCTURAL_NODE_TYPES = new Set([
  'ENTERPRISE',
  'FACILITY',
  'AREA',
  'LINE',
  'DEVICE',
  // Asset Levels the graph database has no equivalent for.
  'SITE',
  'PRODUCTION_UNIT',
  'WORK_CELL',
])

const EQUIPMENT_NODE_TYPES = new Set(['DEVICE_depth_1', 'MACHINE'])

export function getNodeRole(nodeType: string | undefined): NodeRole {
  if (!nodeType) return 'other'
  if (STRUCTURAL_NODE_TYPES.has(nodeType)) return 'structural'
  if (EQUIPMENT_NODE_TYPES.has(nodeType)) return 'equipment'
  if (nodeType === 'DEVICE_depth_2' || nodeType === 'METRIC_GROUP') return 'parameter-group'
  if (nodeType === 'DEVICE_depth_3' || nodeType === 'METRIC') return 'sensor'
  return 'other'
}

/**
 * True when a node has never carried telemetry: an Asset or a Metric the Asset Model
 * declares, or a placeholder the tree probed for. Its payload has to be fetched before
 * it can be shown, and it must not be counted as a stale sensor in the meantime.
 */
export function hasNoTelemetryClock(node: Pick<UnsNode, 'lastUpdated'>): boolean {
  return new Date(node.lastUpdated).getTime() <= 0
}

export function getNodeRoleLabel(role: NodeRole): string {
  switch (role) {
    case 'structural':
      return 'STRUCT'
    case 'equipment':
      return 'EQUIP'
    case 'parameter-group':
      return 'PARAM'
    case 'sensor':
      return 'SENSOR'
    default:
      return 'NODE'
  }
}

export function hasPayloadData(payload: UnsNode['payload']): boolean {
  if (payload === null || payload === undefined) return false
  if (typeof payload === 'object' && !Array.isArray(payload)) {
    return Object.keys(payload).length > 0
  }
  return true
}

export function hasLiveTelemetry(payload: UnsNode['payload']): boolean {
  if (!hasPayloadData(payload) || typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    return false
  }
  return 'value' in payload || 'timestamp' in payload
}

/** Only sensor leaves participate in stale telemetry alerts. */
export function isStaleCandidate(node: Pick<UnsNode, 'nodeType' | 'payload'>): boolean {
  return getNodeRole(node.nodeType) === 'sensor'
}

export function isNodeStale(lastUpdated: string, thresholdMinutes: number): boolean {
  const ts = new Date(lastUpdated).getTime()
  if (Number.isNaN(ts) || ts < Date.UTC(2020, 0, 1)) return false
  return Date.now() - ts > thresholdMinutes * 60 * 1000
}

export function formatAge(iso: string): string {
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts) || ts < Date.UTC(2020, 0, 1)) return 'no telemetry clock'
  const diffMin = Math.floor((Date.now() - ts) / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin} min ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 48) return `${diffHr} hr ago`
  return `${Math.floor(diffHr / 24)} d ago`
}

export function immediateChildTopics(parentTopic: string, descendantTopics: string[]): string[] {
  const prefix = `${parentTopic}/`
  const seen = new Set<string>()
  for (const topic of descendantTopics) {
    if (!topic.startsWith(prefix)) continue
    const rest = topic.slice(prefix.length)
    const segment = rest.split('/')[0]
    if (segment) seen.add(`${parentTopic}/${segment}`)
  }
  return [...seen].sort()
}
