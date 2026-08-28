import type { GraphqlUnsNode } from '../../lib/graphql/types'
import { parseJsonPayload } from '../../lib/uns/payload'
import type { UnsNodeRecord } from './tree-model'

export function graphqlNodesToRecords(nodes: GraphqlUnsNode[]): UnsNodeRecord[] {
  return nodes.map((n) => {
    const parsed = n.payload ? parseJsonPayload(n.payload.data) : ({ ok: false } as const)
    return {
      nodeName: n.nodeName,
      nodeType: n.nodeType,
      namespace: n.namespace,
      payload: parsed.ok ? parsed.value : null,
      created: n.created,
      lastUpdated: n.lastUpdated,
    }
  })
}
