import { expect, test } from 'vitest'
import { emptyTree, mergeGraphNodes, type UnsNodeRecord } from './tree-model'

function node(namespace: string, nodeType = 'DEVICE'): UnsNodeRecord {
  return {
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { rpm: 1 },
    created: '2026-01-01T00:00:00Z',
    lastUpdated: '2026-01-01T00:00:00Z',
  }
}

test('merges root nodes under empty parent', () => {
  const tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  expect(tree.nodes['acme']?.nodeType).toBe('ENTERPRISE')
  expect(tree.childrenByParent['']).toEqual(['acme'])
})

test('merges children under parent path', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  tree = mergeGraphNodes(tree, [node('acme/plant1', 'FACILITY')])
  expect(tree.childrenByParent['acme']).toEqual(['acme/plant1'])
})
