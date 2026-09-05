import { describe, expect, it } from 'vitest'
import type { GraphqlHierarchyTree } from '../../services/graphql/types'
import { hierarchyChildNodes, hierarchyRootNodes } from './map-hierarchy'

const TREE: GraphqlHierarchyTree = {
  enterprise: 'DemoWTP',
  sites: [
    {
      name: 'Site10',
      areas: [
        {
          name: 'RawWater',
          kind: 'production',
          lines: [
            {
              name: 'Train10',
              cells: [{ name: 'P202', machines: ['Machine3050'] }],
            },
          ],
        },
      ],
    },
  ],
}

describe('hierarchyRootNodes', () => {
  it('returns the authored enterprise as the only root', () => {
    const roots = hierarchyRootNodes(TREE)
    expect(roots).toHaveLength(1)
    expect(roots[0]).toEqual(
      expect.objectContaining({
        topic: 'DemoWTP',
        name: 'DemoWTP',
        nodeType: 'ENTERPRISE',
        isLeaf: false,
      }),
    )
  })

  it('returns no roots when the plant tree has no enterprise', () => {
    expect(hierarchyRootNodes({ enterprise: '', sites: [] })).toEqual([])
  })
})

describe('hierarchyChildNodes', () => {
  it('returns authored sites under the enterprise, not MQTT leftovers', () => {
    const children = hierarchyChildNodes(TREE, 'DemoWTP')
    expect(children).toEqual([
      expect.objectContaining({
        topic: 'DemoWTP/Site10',
        name: 'Site10',
        nodeType: 'SITE',
      }),
    ])
  })

  it('walks down to the authored machine', () => {
    expect(hierarchyChildNodes(TREE, 'DemoWTP/Site10/RawWater/Train10/P202')).toEqual([
      expect.objectContaining({
        topic: 'DemoWTP/Site10/RawWater/Train10/P202/Machine3050',
        name: 'Machine3050',
        nodeType: 'MACHINE',
      }),
    ])
  })

  it('returns an empty list for a plant-tree leaf so callers can attach metrics', () => {
    expect(hierarchyChildNodes(TREE, 'DemoWTP/Site10/RawWater/Train10/P202/Machine3050')).toEqual([])
  })

  it('returns null when the topic is not on the plant tree', () => {
    expect(hierarchyChildNodes(TREE, 'test/uns/edge/sim')).toBeNull()
    expect(hierarchyChildNodes(TREE, 'AcmeWater')).toBeNull()
  })
})
