export type UnsNodeRecord = {
  nodeName: string
  nodeType: string
  namespace: string
  payload: unknown
  created: string
  lastUpdated: string
}

export type TreeState = {
  nodes: Record<string, UnsNodeRecord>
  childrenByParent: Record<string, string[]>
  expanded: string[]
  loading: Record<string, boolean>
  errors: Record<string, string>
}

export function emptyTree(): TreeState {
  return {
    nodes: {},
    childrenByParent: {},
    expanded: [],
    loading: {},
    errors: {},
  }
}

export function parentOf(namespace: string): string {
  const i = namespace.lastIndexOf('/')
  return i === -1 ? '' : namespace.slice(0, i)
}

function addChild(list: string[] | undefined, child: string): string[] {
  const next = list ?? []
  if (next.includes(child)) {
    return next
  }
  return [...next, child]
}

export function mergeGraphNodes(tree: TreeState, incoming: UnsNodeRecord[]): TreeState {
  const nodes = { ...tree.nodes }
  const childrenByParent = { ...tree.childrenByParent }
  for (const n of incoming) {
    nodes[n.namespace] = n
    const parent = parentOf(n.namespace)
    childrenByParent[parent] = addChild(childrenByParent[parent], n.namespace)
  }
  return { ...tree, nodes, childrenByParent }
}
