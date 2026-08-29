import { useApolloClient } from '@apollo/client'
import { type MouseEvent } from 'react'
import { useUnsDispatch, useUnsState } from '../../app/UnsProvider'
import { Button } from '../../components/ui/button'
import { isStale } from '../../lib/uns/stale'
import { loadChildren } from './expand-to'
import { useTreeQueries } from './useTreeQueries'

function formatRelative(iso: string, nowMs: number): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) {
    return iso
  }
  const diffSec = Math.round((then - nowMs) / 1000)
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const abs = Math.abs(diffSec)
  if (abs < 60) {
    return rtf.format(diffSec, 'second')
  }
  if (abs < 3600) {
    return rtf.format(Math.round(diffSec / 60), 'minute')
  }
  if (abs < 86400) {
    return rtf.format(Math.round(diffSec / 3600), 'hour')
  }
  return rtf.format(Math.round(diffSec / 86400), 'day')
}

function TreeNode({ namespace, now }: { namespace: string; now: number }) {
  const state = useUnsState()
  const dispatch = useUnsDispatch()
  const client = useApolloClient()
  const node = state.tree.nodes[namespace]
  if (!node) {
    return null
  }
  const expanded = state.tree.expanded.includes(namespace)
  const children = state.tree.childrenByParent[namespace]
  const selected = state.selectedNamespace === namespace
  const stale = isStale(node.lastUpdated, now)
  const err = state.tree.errors[namespace]
  const loading = state.tree.loading[namespace]

  async function onToggle(event: MouseEvent) {
    event.stopPropagation()
    if (expanded) {
      dispatch({ type: 'tree/collapse', namespace })
      return
    }
    if (children === undefined) {
      await loadChildren(client, dispatch, namespace)
    }
    dispatch({ type: 'tree/expand', namespace })
  }

  return (
    <li>
      <div
        role="treeitem"
        aria-selected={selected}
        className={`flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-sm ${
          selected ? 'bg-console-accent/15 text-console-accent' : ''
        } ${stale ? 'opacity-50' : ''}`}
        onClick={() => dispatch({ type: 'ui/select-node', namespace })}
      >
        <button type="button" className="w-4 text-console-muted" onClick={onToggle} aria-label="Expand">
          {expanded ? '▾' : '▸'}
        </button>
        <span className="truncate">{node.nodeName}</span>
        <span className="ml-auto shrink-0 text-xs text-console-muted">
          {node.nodeType} · {formatRelative(node.lastUpdated, now)}
        </span>
      </div>
      {err ? (
        <div className="pl-6 text-xs text-console-danger">
          {err}{' '}
          <Button
            type="button"
            onClick={() => {
              void loadChildren(client, dispatch, namespace)
            }}
          >
            Retry
          </Button>
        </div>
      ) : null}
      {loading ? <div className="pl-6 text-xs text-console-muted">Loading…</div> : null}
      {expanded ? (
        <ul className="pl-4" role="group">
          {(children ?? []).map((child) => (
            <TreeNode key={child} namespace={child} now={now} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function TreePanel() {
  const state = useUnsState()
  const { loadRoots } = useTreeQueries()
  const now = Date.now()
  const roots = state.tree.childrenByParent[''] ?? []

  return (
    <section aria-label="tree" className="flex h-full flex-col overflow-hidden bg-console-bg">
      <h2 className="border-b border-console-border px-3 py-2 text-xs uppercase tracking-wide text-console-muted">
        Namespace
      </h2>
      {state.treeBanner ? (
        <div className="px-3 py-2 text-sm">
          <Button
            type="button"
            onClick={() => {
              loadRoots()
            }}
          >
            Retry
          </Button>
        </div>
      ) : null}
      {roots.length === 0 && !state.tree.loading[''] ? (
        <p className="px-3 py-4 text-sm text-console-muted">
          No nodes yet — waiting for GraphQL / UNS data.
        </p>
      ) : (
        <ul className="flex-1 overflow-auto p-2" role="tree">
          {roots.map((ns) => (
            <TreeNode key={ns} namespace={ns} now={now} />
          ))}
        </ul>
      )}
    </section>
  )
}
