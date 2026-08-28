import { useUnsState } from '../../app/UnsProvider'

export function PayloadPanel() {
  const state = useUnsState()
  const historic = state.historicEvent
  const node = state.selectedNamespace ? state.tree.nodes[state.selectedNamespace] : undefined

  if (historic) {
    return (
      <section aria-label="payload" className="flex h-full flex-col overflow-auto p-3">
        <h2 className="text-sm font-semibold">Historical event</h2>
        <p className="text-xs text-console-muted">
          {historic.topic} · {historic.timestamp} · {historic.publisher}
        </p>
        <pre className="mt-3 overflow-auto text-xs">{JSON.stringify(historic.payload, null, 2)}</pre>
      </section>
    )
  }

  if (!node) {
    return (
      <section aria-label="payload" className="p-3 text-sm text-console-muted">
        Pick a node in the tree.
      </section>
    )
  }

  if (node.payload === null || node.payload === undefined) {
    return (
      <section aria-label="payload" className="p-3">
        <h2 className="text-sm font-semibold">{node.namespace}</h2>
        <p className="text-sm text-console-muted">No payload.</p>
      </section>
    )
  }

  return (
    <section aria-label="payload" className="flex h-full flex-col overflow-auto p-3">
      <h2 className="text-sm font-semibold">{node.namespace}</h2>
      <p className="text-xs text-console-muted">
        {node.nodeType} · created {node.created} · updated {node.lastUpdated}
      </p>
      <pre className="mt-3 overflow-auto text-xs">{JSON.stringify(node.payload, null, 2)}</pre>
    </section>
  )
}
