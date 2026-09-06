/**
 * Guessed ISA-95 topic segments, for a platform with an empty Asset Model.
 *
 * These are guessed payload-folder names. They are a last resort:
 * `lib/uns/map-assets.ts` derives the same part of the tree from authored Metric
 * Definitions, which is right for any plant rather than for one demo. Still here
 * because an install with nothing modelled would otherwise show a tree that stops at
 * the machine, and because deep wildcard queries can exhaust Neo4j.
 */

export const ISA95_PARAMETER_GROUPS = [
  'ProcessValue',
  'Setpoint',
  'Status',
  'Alarm',
  'EVENT',
] as const

export const ISA95_SENSOR_NAMES = [
  'Temperature',
  'Pressure',
  'FlowRate',
  'Level',
  'Humidity',
  'EquipmentStatus',
] as const

export function probeParameterGroupTopics(parentTopic: string): string[] {
  return ISA95_PARAMETER_GROUPS.map((segment) => `${parentTopic}/${segment}`)
}

export function probeSensorTopics(parentTopic: string): string[] {
  return ISA95_SENSOR_NAMES.map((segment) => `${parentTopic}/${segment}`)
}

export function isParameterGroupTopic(topic: string): boolean {
  const tail = topic.split('/').pop() ?? ''
  return (ISA95_PARAMETER_GROUPS as readonly string[]).includes(tail)
}

function segmentName(topic: string): string {
  return topic.split('/').pop() ?? topic
}

/** Placeholder nodes so the tree expands even when Neo4j batch queries fail. */
export function syntheticParameterGroupNodes(parentTopic: string): import('../../types/uns').UnsNode[] {
  return probeParameterGroupTopics(parentTopic).map((topic) => ({
    topic,
    name: segmentName(topic),
    namespace: topic,
    nodeType: 'DEVICE_depth_2',
    payload: null,
    lastUpdated: new Date(0).toISOString(),
    isLeaf: false,
    isSparkplug: false,
  }))
}

export function syntheticSensorNodes(parentTopic: string): import('../../types/uns').UnsNode[] {
  return probeSensorTopics(parentTopic).map((topic) => ({
    topic,
    name: segmentName(topic),
    namespace: topic,
    nodeType: 'DEVICE_depth_3',
    payload: null,
    lastUpdated: new Date(0).toISOString(),
    isLeaf: true,
    isSparkplug: false,
  }))
}
