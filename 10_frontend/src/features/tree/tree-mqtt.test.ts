import { expect, test } from 'vitest'
import { applyMqttToTree } from './tree-mqtt'
import { emptyTree, mergeGraphNodes, type UnsNodeRecord } from './tree-model'

function node(namespace: string, nodeType = 'LINE'): UnsNodeRecord {
  return {
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { rpm: 1 },
    created: '2026-01-01T00:00:00Z',
    lastUpdated: '2026-01-01T00:00:00Z',
  }
}

test('patches loaded uns node payload and timestamp', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme/l1')])
  tree = applyMqttToTree(tree, {
    topic: 'acme/l1',
    payload: { rpm: 9 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(tree.nodes['acme/l1']?.payload).toEqual({ rpm: 9 })
  expect(tree.nodes['acme/l1']?.lastUpdated).toBe('2026-08-28T12:00:00Z')
})

test('does not insert sparkplug into the tree', () => {
  const tree = applyMqttToTree(emptyTree(), {
    topic: 'spBv1.0/G/NDATA/E',
    payload: { x: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(tree.nodes['spBv1.0/G/NDATA/E']).toBeUndefined()
})

test('inserts new uns child only if parent is expanded', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  const closed = applyMqttToTree(tree, {
    topic: 'acme/plant1',
    payload: { a: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(closed.nodes['acme/plant1']).toBeUndefined()

  tree = { ...tree, expanded: ['acme'] }
  const open = applyMqttToTree(tree, {
    topic: 'acme/plant1',
    payload: { a: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(open.nodes['acme/plant1']?.payload).toEqual({ a: 1 })
  expect(open.childrenByParent['acme']).toContain('acme/plant1')
})
