import { appendFeed, type FeedItem } from '../features/feed/feed-buffer'
import { applyMqttToTree } from '../features/tree/tree-mqtt'
import { emptyTree, mergeGraphNodes, type TreeState, type UnsNodeRecord } from '../features/tree/tree-model'
import { parseJsonPayload } from '../lib/uns/payload'
import { isSparkplugTopic } from '../lib/uns/sparkplug'

export type HistoricEventView = {
  topic: string
  timestamp: string
  publisher: string
  payload: unknown
}

export type UnsState = {
  tree: TreeState
  selectedNamespace: string | null
  historicEvent: HistoricEventView | null
  feed: FeedItem[]
  feedPaused: boolean
  httpOk: boolean
  wsOk: boolean
  treeBanner: string | null
}

export type UnsAction =
  | { type: 'tree/load-start'; parent: string }
  | { type: 'tree/load-ok'; parent: string; nodes: UnsNodeRecord[] }
  | { type: 'tree/load-err'; parent: string; message: string }
  | { type: 'tree/expand'; namespace: string }
  | { type: 'tree/collapse'; namespace: string }
  | { type: 'tree/banner'; message: string | null }
  | { type: 'ui/select-node'; namespace: string | null }
  | { type: 'ui/select-historic-event'; event: HistoricEventView | null }
  | { type: 'feed/pause'; paused: boolean }
  | {
      type: 'feed/mqtt'
      topic: string
      typename: 'JSONPayload' | 'BytesPayload' | 'unknown'
      data: unknown
      timestamp: string
      id?: string
    }
  | { type: 'conn/http'; ok: boolean }
  | { type: 'conn/ws'; ok: boolean }

export function initialUnsState(): UnsState {
  return {
    tree: emptyTree(),
    selectedNamespace: null,
    historicEvent: null,
    feed: [],
    feedPaused: false,
    httpOk: false,
    wsOk: false,
    treeBanner: null,
  }
}

function withExpanded(tree: TreeState, namespace: string): TreeState {
  if (tree.expanded.includes(namespace)) {
    return tree
  }
  return { ...tree, expanded: [...tree.expanded, namespace] }
}

export function unsReducer(state: UnsState, action: UnsAction): UnsState {
  switch (action.type) {
    case 'tree/load-start':
      return {
        ...state,
        tree: {
          ...state.tree,
          loading: { ...state.tree.loading, [action.parent]: true },
          errors: { ...state.tree.errors, [action.parent]: '' },
        },
      }
    case 'tree/load-ok':
      return {
        ...state,
        httpOk: true,
        treeBanner: action.parent === '' ? null : state.treeBanner,
        tree: {
          ...mergeGraphNodes(state.tree, action.nodes),
          loading: { ...state.tree.loading, [action.parent]: false },
          errors: { ...state.tree.errors, [action.parent]: '' },
        },
      }
    case 'tree/load-err':
      return {
        ...state,
        httpOk: false,
        treeBanner: action.parent === '' ? action.message : state.treeBanner,
        tree: {
          ...state.tree,
          loading: { ...state.tree.loading, [action.parent]: false },
          errors: { ...state.tree.errors, [action.parent]: action.message },
        },
      }
    case 'tree/expand':
      return { ...state, tree: withExpanded(state.tree, action.namespace) }
    case 'tree/collapse':
      return {
        ...state,
        tree: {
          ...state.tree,
          expanded: state.tree.expanded.filter((n) => n !== action.namespace),
        },
      }
    case 'tree/banner':
      return { ...state, treeBanner: action.message }
    case 'ui/select-node':
      return { ...state, selectedNamespace: action.namespace, historicEvent: null }
    case 'ui/select-historic-event':
      return { ...state, historicEvent: action.event }
    case 'feed/pause':
      return { ...state, feedPaused: action.paused }
    case 'conn/http':
      return { ...state, httpOk: action.ok }
    case 'conn/ws':
      return { ...state, wsOk: action.ok }
    case 'feed/mqtt': {
      const id = action.id ?? crypto.randomUUID()
      const sparkplug =
        action.typename === 'BytesPayload' || isSparkplugTopic(action.topic)
      if (sparkplug) {
        const row: FeedItem = {
          id,
          topic: action.topic,
          timestamp: action.timestamp,
          kind: 'sparkplug',
          preview: null,
        }
        return { ...state, feed: appendFeed(state.feed, row, state.feedPaused) }
      }
      const parsed = parseJsonPayload(action.data)
      if (!parsed.ok) {
        const row: FeedItem = {
          id,
          topic: action.topic,
          timestamp: action.timestamp,
          kind: 'invalid-json',
          preview: null,
        }
        return { ...state, feed: appendFeed(state.feed, row, state.feedPaused) }
      }
      const row: FeedItem = {
        id,
        topic: action.topic,
        timestamp: action.timestamp,
        kind: 'uns',
        preview: parsed.value,
      }
      return {
        ...state,
        feed: appendFeed(state.feed, row, state.feedPaused),
        tree: applyMqttToTree(state.tree, {
          topic: action.topic,
          payload: parsed.value,
          timestamp: action.timestamp,
        }),
      }
    }
  }
}
