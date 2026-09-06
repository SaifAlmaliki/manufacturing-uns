/**
 * The authored Asset Model, turned into tree nodes and node properties.
 *
 * The plant hierarchy is declared in Postgres; the graph database only records what
 * has been published (ADR-0003). So the tree asks the Asset Model first, and this is
 * where its answer becomes a UnsNode: one node per Asset down the branch, then — below
 * the deepest Asset — one node per topic segment the Metric Definitions declare.
 *
 * That replaces guessing. The segments below a machine used to come from a
 * hardcoded list of demo payload folders, which was wrong for every other plant.
 */

import type { UnsNode } from '../../types/uns'
import { parseJsonPayload } from './payload'
import type {
  GraphqlAssetNode,
  GraphqlMetricDefinition,
  GraphqlTopicContext,
} from '../../services/graphql/types'

/** A topic segment below an Asset that has further segments under it. */
export const METRIC_GROUP_NODE_TYPE = 'METRIC_GROUP'
/** A topic segment below an Asset that carries the payload itself. */
export const METRIC_NODE_TYPE = 'METRIC'

/**
 * Asset Model nodes are declared, not observed, so they have no telemetry clock.
 * Epoch keeps them out of the stale-node count and marks them for hydration from
 * the historian on selection.
 */
const NO_TELEMETRY_YET = new Date(0).toISOString()

/** Undefined and empty are both "nothing authored", and neither belongs in a table. */
function withoutBlanks(entries: Array<[string, string | number | null | undefined]>): Record<string, string> {
  const properties: Record<string, string> = {}
  for (const [key, value] of entries) {
    if (value === null || value === undefined || value === '') continue
    properties[key] = String(value)
  }
  return properties
}

/** Site-specific facts an engineer put on the Asset, flattened for display. */
function attributeProperties(attributes: { data: unknown } | null | undefined): Record<string, string> {
  const parsed = attributes ? parseJsonPayload(attributes.data) : { ok: false as const }
  if (!parsed.ok || typeof parsed.value !== 'object' || parsed.value === null || Array.isArray(parsed.value)) {
    return {}
  }
  return withoutBlanks(
    Object.entries(parsed.value as Record<string, unknown>).map(([key, value]) => [
      key,
      typeof value === 'object' ? JSON.stringify(value) : (value as string | number | null),
    ]),
  )
}

export function assetProperties(asset: GraphqlAssetNode): Record<string, string> {
  return {
    ...withoutBlanks([
      ['Asset Level', asset.level],
      ['Description', asset.description],
      ['Manufacturer', asset.manufacturer],
      ['Model', asset.modelNumber],
      ['Serial', asset.serialNumber],
      ['Criticality', asset.criticality],
    ]),
    ...attributeProperties(asset.attributes),
  }
}

export function assetToUnsNode(asset: GraphqlAssetNode): UnsNode {
  return {
    topic: asset.path,
    // The authored name is the point of the Asset Model: 'Filler 3', not 'G1'.
    name: asset.name || asset.segment,
    namespace: asset.path,
    nodeType: asset.level,
    payload: null,
    lastUpdated: NO_TELEMETRY_YET,
    // An Asset is expandable until asked: its children may be Assets or Metrics.
    isLeaf: false,
    isSparkplug: false,
    properties: assetProperties(asset),
  }
}

/**
 * The topic segments of a Metric Key, without the payload leaf.
 *
 * A Metric Key is the topic below the Asset plus the leaf inside the payload —
 * 'ProcessValue/Temperature/value' is the topic '…/ProcessValue/Temperature'
 * carrying `{"value": …}` — so the last segment is never a node in the tree.
 */
function topicPartOf(definition: GraphqlMetricDefinition): string {
  return definition.metricKey.split('/').slice(0, -1).join('/')
}

type MetricChild = {
  /** No Metric Key goes deeper than this segment, so it is where the payload lands. */
  isLeaf: boolean
  displayName?: string | null
  definition?: GraphqlMetricDefinition
}

export function metricProperties(definition: GraphqlMetricDefinition): Record<string, string> {
  return withoutBlanks([
    ['Metric Key', definition.metricKey],
    ['Unit of Measure', definition.unitOfMeasure],
    ['Min', definition.minValue],
    ['Max', definition.maxValue],
  ])
}

/**
 * The children of `parentTopic` that the Asset Model declares below its Asset.
 *
 * `context` is the Enrichment for `parentTopic` itself: it names the Asset that
 * publishes it and carries every Metric Definition that could apply. Everything below
 * the Asset is derived from those Metric Keys, so a plant that publishes
 * 'Setpoint/Flow' gets that node and nothing it does not publish.
 */
export function metricChildNodes(parentTopic: string, context: GraphqlTopicContext | null): UnsNode[] {
  if (!context) return []

  const prefix = context.metricPath ? `${context.metricPath}/` : ''
  const children = new Map<string, MetricChild>()

  for (const definition of context.metricDefinitions) {
    const topicPart = topicPartOf(definition)
    if (!topicPart || !topicPart.startsWith(prefix)) continue

    const rest = topicPart.slice(prefix.length)
    const [segment] = rest.split('/')
    if (!segment) continue

    const terminatesHere = rest === segment
    const existing = children.get(segment)
    children.set(segment, {
      // Only a leaf while nothing deeper has been seen: a segment can carry both its
      // own payload and further segments, and then it is still expandable.
      isLeaf: terminatesHere && (existing?.isLeaf ?? true),
      // Later definitions win, matching the Asset-specific-last ordering the server
      // returns them in.
      displayName: terminatesHere ? definition.displayName : existing?.displayName,
      definition: terminatesHere ? definition : existing?.definition,
    })
  }

  return [...children.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([segment, child]) => ({
      topic: `${parentTopic}/${segment}`,
      name: child.displayName || segment,
      namespace: `${parentTopic}/${segment}`,
      nodeType: child.isLeaf ? METRIC_NODE_TYPE : METRIC_GROUP_NODE_TYPE,
      payload: null,
      lastUpdated: NO_TELEMETRY_YET,
      isLeaf: child.isLeaf,
      isSparkplug: false,
      properties: child.definition ? metricProperties(child.definition) : undefined,
    }))
}

/**
 * What the Asset Model knows about one topic, as display properties.
 *
 * This is the read-time Enrichment the console shows next to a live payload: the name
 * of the Line and the Machine, and the unit the number is in. Observed topics get it
 * too — being in the graph database and being modelled are independent.
 */
export function topicContextProperties(context: GraphqlTopicContext): Record<string, string> {
  const definition = context.metricDefinitions.find(
    (candidate) => topicPartOf(candidate) === context.metricPath,
  )
  return {
    ...withoutBlanks([
      ['Enterprise', context.enterprise],
      ['Site', context.site],
      ['Area', context.area],
      ['Production Unit', context.productionUnit],
      ['Line', context.line],
      ['Work Cell', context.workCell],
      ['Machine', context.machine],
    ]),
    ...assetProperties(context.asset),
    ...(definition ? metricProperties(definition) : {}),
  }
}
