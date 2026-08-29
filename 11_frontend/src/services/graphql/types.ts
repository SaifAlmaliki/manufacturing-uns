export type GraphqlUnsNode = {
  nodeName: string
  nodeType: string
  namespace: string
  payload: { data: unknown } | null
  created: string
  lastUpdated: string
}

export type GraphqlHistoricalEvent = {
  publisher: string
  timestamp: string
  topic: string
  payload: { data: unknown } | null
}

export type GraphqlMqttMessage = {
  topic: string
  payload:
    | { __typename: 'JSONPayload'; data: unknown }
    | { __typename: 'BytesPayload'; data: string }
    | null
}

export type GraphqlKafkaMessage = {
  topic: string
  payload: { data: unknown } | null
}

export type GraphqlSpbMetric = {
  name: string
  alias?: number | null
  timestamp: string
  datatype: string
  isHistorical?: boolean | null
  isTransient?: boolean | null
  isNull?: boolean | null
  value?: {
    __typename?: string
    data?: string
  } | null
}

export type GraphqlSpbNode = {
  topic: string
  timestamp: string
  metrics: GraphqlSpbMetric[]
  seq: number
  uuid?: string | null
  body?: string | null
}
