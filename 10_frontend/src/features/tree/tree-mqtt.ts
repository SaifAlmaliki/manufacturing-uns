import { isSparkplugTopic } from '../../lib/uns/sparkplug'
import { parentOf, type TreeState, type UnsNodeRecord } from './tree-model'

export type MqttTreeEvent = {
  topic: string
  payload: unknown
  timestamp: string
}

export function applyMqttToTree(tree: TreeState, event: MqttTreeEvent): TreeState {
  if (isSparkplugTopic(event.topic)) {
    return tree
  }
  const existing = tree.nodes[event.topic]
  if (existing) {
    const patched: UnsNodeRecord = {
      ...existing,
      payload: event.payload,
      lastUpdated: event.timestamp,
    }
    return { ...tree, nodes: { ...tree.nodes, [event.topic]: patched } }
  }
  const parent = parentOf(event.topic)
  if (!tree.expanded.includes(parent)) {
    return tree
  }
  const leaf: UnsNodeRecord = {
    nodeName: event.topic.split('/').at(-1) ?? event.topic,
    nodeType: 'DEVICE',
    namespace: event.topic,
    payload: event.payload,
    created: event.timestamp,
    lastUpdated: event.timestamp,
  }
  const siblings = tree.childrenByParent[parent] ?? []
  const children = siblings.includes(event.topic) ? siblings : [...siblings, event.topic]
  return {
    ...tree,
    nodes: { ...tree.nodes, [event.topic]: leaf },
    childrenByParent: { ...tree.childrenByParent, [parent]: children },
  }
}
