import type { HistoricEvent, MqttMessage, SparkplugMetric, SparkplugNode, UnsNode } from '../../types/uns'
import { parseJsonPayload } from './payload'
import { isSparkplugTopic, parseSparkplugTopic } from './sparkplug'
import type {
  GraphqlHistoricalEvent,
  GraphqlMqttMessage,
  GraphqlSpbMetric,
  GraphqlSpbNode,
  GraphqlUnsNode,
} from '../../services/graphql/types'

type PayloadValue = Record<string, unknown> | string | number | boolean | null

function asPayloadValue(value: unknown): PayloadValue {
  if (value === null) {
    return null
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  if (typeof value === 'object') {
    return value as Record<string, unknown>
  }
  return String(value)
}

const LEAF_NODE_TYPES = new Set([
  'DEVICE',
  'NESTED_ATTRIBUTE',
  'DEVICE_depth_2',
  'DEVICE_depth_3',
])

export function graphqlUnsNodeToUnsNode(node: GraphqlUnsNode): UnsNode {
  const parsed = node.payload ? parseJsonPayload(node.payload.data) : { ok: false as const }
  return {
    topic: node.namespace,
    name: node.nodeName,
    namespace: node.namespace,
    nodeType: node.nodeType,
    payload: parsed.ok ? asPayloadValue(parsed.value) : null,
    lastUpdated: node.lastUpdated,
    isLeaf: LEAF_NODE_TYPES.has(node.nodeType),
    isSparkplug: isSparkplugTopic(node.namespace),
  }
}

export function graphqlHistoricalEventToHistoricEvent(event: GraphqlHistoricalEvent): HistoricEvent {
  const parsed = event.payload ? parseJsonPayload(event.payload.data) : { ok: false as const }
  return {
    id: `${event.topic}:${event.timestamp}`,
    topic: event.topic,
    payload: parsed.ok ? asPayloadValue(parsed.value) : null,
    timestamp: event.timestamp,
    publisher: event.publisher,
  }
}

export function graphqlMqttMessageToMqttMessage(message: GraphqlMqttMessage): MqttMessage {
  let payload: PayloadValue = null
  if (message.payload?.__typename === 'JSONPayload') {
    const parsed = parseJsonPayload(message.payload.data)
    payload = parsed.ok ? asPayloadValue(parsed.value) : asPayloadValue(message.payload.data)
  } else if (message.payload?.__typename === 'BytesPayload') {
    payload = message.payload.data
  }

  return {
    id: `${message.topic}:${Date.now()}`,
    topic: message.topic,
    payload,
    timestamp: new Date().toISOString(),
    isSparkplug: isSparkplugTopic(message.topic),
  }
}

function spbMetricValue(metric: GraphqlSpbMetric): unknown {
  const value = metric.value
  if (!value) {
    return null
  }
  if ('data' in value && typeof value.data === 'string') {
    if (metric.datatype === 'Boolean') {
      return value.data === 'true'
    }
    if (['Int8', 'Int16', 'Int32', 'Int64', 'UInt8', 'UInt16', 'UInt32', 'UInt64', 'Float', 'Double'].includes(metric.datatype)) {
      const num = Number(value.data)
      return Number.isNaN(num) ? value.data : num
    }
    return value.data
  }
  if ('data' in value && value.__typename === 'BytesPayload') {
    return value.data
  }
  return null
}

function graphqlSpbMetricToSparkplugMetric(metric: GraphqlSpbMetric): SparkplugMetric {
  const value = spbMetricValue(metric)
  const isBinary = metric.datatype === 'Bytes' || metric.datatype === 'File'
  return {
    name: metric.name,
    alias: metric.alias ?? undefined,
    datatype: metric.datatype as SparkplugMetric['datatype'],
    value,
    timestamp: metric.timestamp,
    isHistorical: metric.isHistorical ?? undefined,
    isTransient: metric.isTransient ?? undefined,
    isBinary,
    binaryByteSize: isBinary && typeof value === 'string' ? value.length / 2 : undefined,
  }
}

export function graphqlSpbNodeToSparkplugNode(node: GraphqlSpbNode): SparkplugNode {
  const { groupId, edgeNodeId, deviceId } = parseSparkplugTopic(node.topic)
  return {
    groupId,
    edgeNodeId,
    deviceId,
    topic: node.topic,
    metrics: node.metrics.map(graphqlSpbMetricToSparkplugMetric),
    sequenceNumber: node.seq,
    timestamp: node.timestamp,
    online: true,
  }
}
