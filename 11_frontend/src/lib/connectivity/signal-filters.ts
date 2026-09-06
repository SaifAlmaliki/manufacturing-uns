import type {
  GraphqlSignalSemanticClass,
  GraphqlSubscribedSignal,
} from '../../services/graphql/types'

export type SubscribedSignalFilters = {
  search?: string
  serverId?: string
  missingUnit?: boolean
  semanticClass?: GraphqlSignalSemanticClass
  label?: string
}

function isMissingUnit(unitOfMeasure: string | null | undefined): boolean {
  return unitOfMeasure == null || unitOfMeasure === ''
}

function matchesSearch(row: GraphqlSubscribedSignal, search: string): boolean {
  const q = search.trim().toLowerCase()
  if (!q) return true
  return (
    row.displayName.toLowerCase().includes(q) ||
    row.mqttTopic.toLowerCase().includes(q) ||
    row.nodeId.toLowerCase().includes(q) ||
    row.serverName.toLowerCase().includes(q)
  )
}

export function filterSubscribedSignals(
  rows: GraphqlSubscribedSignal[],
  filters: SubscribedSignalFilters,
): GraphqlSubscribedSignal[] {
  const { search, serverId, missingUnit, semanticClass, label } = filters

  return rows.filter((row) => {
    if (search !== undefined && !matchesSearch(row, search)) return false
    if (serverId !== undefined && row.serverId !== serverId) return false
    if (missingUnit && !isMissingUnit(row.unitOfMeasure)) return false
    if (semanticClass !== undefined && row.semanticClass !== semanticClass) return false
    if (label !== undefined && !(row.labels ?? []).includes(label)) return false
    return true
  })
}
