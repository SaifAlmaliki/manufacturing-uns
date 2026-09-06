import type { AlarmCategory, AlarmConditionType } from '../../types/alarm'
import type { GraphqlSignalDataType, GraphqlSubscribedSignal } from '../../services/graphql/types'

/** Collector payloads for subscribed OPC UA tags are `{ value, timestamp, source }`. */
export const SIGNAL_METRIC_FIELD = 'value'

export type SignalRuleDefaults = {
  topic: string
  metricField: string
  unit: string
  suggestedName: string
  category: AlarmCategory
  condition: AlarmConditionType
}

type SignalHint = Pick<
  GraphqlSubscribedSignal,
  'displayName' | 'mqttTopic' | 'unitOfMeasure' | 'dataType' | 'assetDisplayName'
>

const CATEGORY_HINTS: { needle: RegExp; category: AlarmCategory }[] = [
  { needle: /temp|celsius|fahrenheit/, category: 'TEMPERATURE' },
  { needle: /press|bar|psi/, category: 'PRESSURE' },
  { needle: /vibrat|rms/, category: 'VIBRATION' },
  { needle: /flow/, category: 'FLOW_RATE' },
]

export function defaultsFromSignal(signal: SignalHint): SignalRuleDefaults {
  const haystack = [signal.displayName, signal.mqttTopic, signal.assetDisplayName ?? '']
    .join(' ')
    .toLowerCase()
  const category =
    CATEGORY_HINTS.find((hint) => hint.needle.test(haystack))?.category ?? 'THRESHOLD'
  const asset = signal.assetDisplayName?.trim()
  return {
    topic: signal.mqttTopic,
    metricField: SIGNAL_METRIC_FIELD,
    unit: signal.unitOfMeasure ?? '',
    suggestedName: asset ? `${asset} ${signal.displayName}` : signal.displayName,
    category,
    condition: conditionForDataType(signal.dataType),
  }
}

export function conditionForDataType(dataType?: GraphqlSignalDataType | null): AlarmConditionType {
  if (dataType === 'Boolean') return 'EQUALS'
  if (dataType === 'String') return 'CONTAINS'
  return 'GREATER_THAN'
}

const NUMERIC_CONDITIONS: { label: string; value: AlarmConditionType }[] = [
  { label: 'Greater than', value: 'GREATER_THAN' },
  { label: 'Less than', value: 'LESS_THAN' },
  { label: 'Equals', value: 'EQUALS' },
  { label: 'Not equals', value: 'NOT_EQUALS' },
  { label: 'Range outside', value: 'RANGE_OUTSIDE' },
  { label: 'Stale timeout', value: 'STALE_TIMEOUT' },
]

const BOOLEAN_CONDITIONS: { label: string; value: AlarmConditionType }[] = [
  { label: 'Equals', value: 'EQUALS' },
  { label: 'Not equals', value: 'NOT_EQUALS' },
  { label: 'Stale timeout', value: 'STALE_TIMEOUT' },
]

const STRING_CONDITIONS: { label: string; value: AlarmConditionType }[] = [
  { label: 'Contains', value: 'CONTAINS' },
  { label: 'Equals', value: 'EQUALS' },
  { label: 'Not equals', value: 'NOT_EQUALS' },
  { label: 'Stale timeout', value: 'STALE_TIMEOUT' },
]

export function conditionsForDataType(
  dataType?: GraphqlSignalDataType | null,
): { label: string; value: AlarmConditionType }[] {
  if (dataType === 'Boolean') return BOOLEAN_CONDITIONS
  if (dataType === 'String') return STRING_CONDITIONS
  return NUMERIC_CONDITIONS
}

export function signalRowKey(signal: Pick<GraphqlSubscribedSignal, 'serverId' | 'nodeId'>): string {
  return `${signal.serverId}:${signal.nodeId}`
}
