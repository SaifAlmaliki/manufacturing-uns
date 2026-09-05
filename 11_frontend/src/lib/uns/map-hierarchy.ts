/**
 * The authored plant hierarchy (plant.yaml via getHierarchy), as tree nodes.
 *
 * Condition Monitoring, the dashboard tree, and Connectivity pick from this
 * tree. The graph database still answers "what was published"; it must not
 * invent a second plant structure (ADR-0005).
 */

import type { GraphqlHierarchyTree } from '../../services/graphql/types'
import type { UnsNode } from '../../types/uns'
import { joinSegments } from './topics'

const NO_TELEMETRY_YET = new Date(0).toISOString()

function plantNode(topic: string, name: string, nodeType: string): UnsNode {
  return {
    topic,
    name,
    namespace: topic,
    nodeType,
    payload: null,
    lastUpdated: NO_TELEMETRY_YET,
    isLeaf: false,
    isSparkplug: false,
    properties: { 'Asset Level': nodeType },
  }
}

/** The enterprise is the only platform root when a plant tree has been authored. */
export function hierarchyRootNodes(tree: GraphqlHierarchyTree): UnsNode[] {
  if (!tree.enterprise) return []
  return [plantNode(tree.enterprise, tree.enterprise, 'ENTERPRISE')]
}

/**
 * Direct children of `parentTopic` on the plant tree.
 *
 * `[]` means the topic is on the tree but has no authored child (a Machine, or
 * an empty Cell) — callers may then attach Metric nodes.
 * `null` means the topic is not on the plant tree at all.
 */
export function hierarchyChildNodes(
  tree: GraphqlHierarchyTree,
  parentTopic: string,
): UnsNode[] | null {
  if (!tree.enterprise) return null
  if (parentTopic === tree.enterprise) {
    return tree.sites.map((site) => plantNode(joinSegments(tree.enterprise, site.name), site.name, 'SITE'))
  }

  for (const site of tree.sites) {
    const siteTopic = joinSegments(tree.enterprise, site.name)
    if (parentTopic === siteTopic) {
      return site.areas.map((area) => plantNode(joinSegments(siteTopic, area.name), area.name, 'AREA'))
    }
    for (const area of site.areas) {
      const areaTopic = joinSegments(siteTopic, area.name)
      if (parentTopic === areaTopic) {
        return area.lines.map((line) => plantNode(joinSegments(areaTopic, line.name), line.name, 'LINE'))
      }
      for (const line of area.lines) {
        const lineTopic = joinSegments(areaTopic, line.name)
        if (parentTopic === lineTopic) {
          return line.cells.map((cell) =>
            plantNode(joinSegments(lineTopic, cell.name), cell.name, 'WORK_CELL'),
          )
        }
        for (const cell of line.cells) {
          const cellTopic = joinSegments(lineTopic, cell.name)
          if (parentTopic === cellTopic) {
            return cell.machines.map((machine) =>
              plantNode(joinSegments(cellTopic, machine), machine, 'MACHINE'),
            )
          }
          for (const machine of cell.machines) {
            if (parentTopic === joinSegments(cellTopic, machine)) return []
          }
        }
      }
    }
  }
  return null
}
