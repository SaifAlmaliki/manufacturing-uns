/** Known ISA-95 topic segments used by 99_simulator — avoids Neo4j OOM from deep wildcards. */

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
