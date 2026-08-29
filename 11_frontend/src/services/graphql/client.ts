/**
 * GraphQL client for 07_uns_graphql (HTTP queries + graphql-transport-ws subscriptions)
 */

import {
  graphqlHistoricalEventToHistoricEvent,
  graphqlMqttMessageToMqttMessage,
  graphqlSpbNodeToSparkplugNode,
  graphqlUnsNodeToUnsNode,
} from '../../lib/uns/map-nodes'
import { mqttTopicInput, mqttTopicInputs, childrenTopic, topicDepth } from '../../lib/uns/topics'
import {
  isParameterGroupTopic,
  probeParameterGroupTopics,
  probeSensorTopics,
} from '../../lib/uns/isa95-probe'
import type {
  HistoricEvent,
  KafkaMessage,
  MqttMessage,
  SparkplugNode,
  SystemHealthInfo,
  UnsNode,
} from '../../types/uns'
import {
  GET_HISTORIC_EVENTS_BY_PROPERTY_QUERY,
  GET_HISTORIC_EVENTS_BY_PUBLISHERS_QUERY,
  GET_HISTORIC_EVENTS_IN_TIME_RANGE_QUERY,
  GET_SPB_NODES_BY_METRIC_QUERY,
  GET_UNS_NODES_BY_PROPERTY_QUERY,
  GET_UNS_NODES_QUERY,
  SUBSCRIBE_KAFKA_MESSAGES,
  SUBSCRIBE_MQTT_MESSAGES,
} from './queries'
import type {
  GraphqlHistoricalEvent,
  GraphqlKafkaMessage,
  GraphqlMqttMessage,
  GraphqlSpbNode,
  GraphqlUnsNode,
} from './types'

type BinaryOperator = 'OR' | 'AND' | 'NOT'

export class UnsGraphQLClient {
  private httpUrl: string
  private wsUrl: string
  private ws: WebSocket | null = null
  private wsConnected = false
  private wsProtocolReady = false
  private isLiveBackend = false
  private lastPingMs = 0
  private healthListeners = new Set<(health: SystemHealthInfo) => void>()
  private activeWsSubscriptions = new Map<string, (data: unknown) => void>()
  private mqttMessageSubs = new Map<
    string,
    { topics: string[]; onMessage: (msg: MqttMessage) => void; wsSubId?: string }
  >()

  constructor(httpUrl = '/graphql', wsUrl?: string) {
    this.httpUrl = httpUrl
    this.wsUrl =
      wsUrl ||
      (typeof window !== 'undefined'
        ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/graphql`
        : 'ws://localhost:8000/graphql')
    this.initWebSocket()
  }

  public setUrls(httpUrl: string, wsUrl: string) {
    this.httpUrl = httpUrl
    this.wsUrl = wsUrl
    this.initWebSocket()
  }

  private initWebSocket() {
    if (typeof window === 'undefined') {
      return
    }

    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }

    try {
      this.ws = new WebSocket(this.wsUrl, 'graphql-transport-ws')

      this.ws.onopen = () => {
        this.wsConnected = true
        this.wsProtocolReady = false
        this.ws?.send(JSON.stringify({ type: 'connection_init' }))
        this.notifyHealth()
      }

      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'connection_ack') {
            this.wsProtocolReady = true
            this.resubscribeMqttMessages()
            this.notifyHealth()
          }
          if (msg.type === 'next' && msg.id && this.activeWsSubscriptions.has(msg.id)) {
            this.activeWsSubscriptions.get(msg.id)?.(msg.payload?.data)
          }
        } catch {
          // ignore
        }
      }

      this.ws.onerror = () => {
        this.wsConnected = false
        this.wsProtocolReady = false
        this.notifyHealth()
      }

      this.ws.onclose = () => {
        this.wsConnected = false
        this.wsProtocolReady = false
        this.notifyHealth()
      }
    } catch {
      this.wsConnected = false
    }
  }

  private async executeQuery<T>(
    query: string,
    variables: Record<string, unknown> = {},
  ): Promise<{ data: T | null; error?: string }> {
    const t0 = performance.now()
    try {
      const response = await fetch(this.httpUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ query, variables }),
      })

      this.lastPingMs = Math.round(performance.now() - t0)

      if (response.ok) {
        const json = await response.json()
        if (json.data) {
          this.isLiveBackend = true
          this.notifyHealth()
          return { data: json.data as T }
        }
        if (json.errors?.length > 0) {
          return { data: null, error: json.errors[0].message as string }
        }
      }
    } catch {
      this.isLiveBackend = false
    }

    this.notifyHealth()
    return { data: null, error: 'GraphQL endpoint unreachable' }
  }

  public async getUnsNodes(topics: string[]): Promise<UnsNode[]> {
    const res = await this.executeQuery<{ getUnsNodes: GraphqlUnsNode[] }>(GET_UNS_NODES_QUERY, {
      topics: mqttTopicInputs(topics),
    })
    if (res.data?.getUnsNodes) {
      return res.data.getUnsNodes.map(graphqlUnsNodeToUnsNode)
    }
    return []
  }

  /**
   * Load direct children of a tree node. Uses exact ISA-95 segment probes when wildcard
   * queries would OOM Neo4j on deep paths (e.g. G1/+).
   */
  public async getUnsNodeChildren(parentTopic: string): Promise<UnsNode[]> {
    // Wildcard "+" queries under equipment (G1/+) OOM Neo4j — use exact ISA-95 probes instead.
    const useWildcard = topicDepth(parentTopic) < 6
    if (useWildcard) {
      const direct = await this.getUnsNodes([childrenTopic(parentTopic)])
      if (direct.length > 0) {
        return direct
      }
    }

    const parameterGroups = await this.getUnsNodes(probeParameterGroupTopics(parentTopic))
    if (parameterGroups.length > 0) {
      return parameterGroups
    }

    if (isParameterGroupTopic(parentTopic)) {
      return this.getUnsNodes(probeSensorTopics(parentTopic))
    }

    return []
  }

  public async getHistoricEvents(
    topic: string,
    fromDatetime?: string,
    toDatetime?: string,
  ): Promise<HistoricEvent[]> {
    const res = await this.executeQuery<{ getHistoricEventsInTimeRange: GraphqlHistoricalEvent[] }>(
      GET_HISTORIC_EVENTS_IN_TIME_RANGE_QUERY,
      {
        topics: [mqttTopicInput(topic)],
        fromDatetime,
        toDatetime,
      },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    if (res.data?.getHistoricEventsInTimeRange) {
      return res.data.getHistoricEventsInTimeRange.map(graphqlHistoricalEventToHistoricEvent)
    }
    return []
  }

  public async getHistoricEventsByPublishers(
    publishers: string[],
    topics?: string[],
    fromDatetime?: string,
    toDatetime?: string,
  ): Promise<HistoricEvent[]> {
    const res = await this.executeQuery<{ getHistoricEventsByPublishers: GraphqlHistoricalEvent[] }>(
      GET_HISTORIC_EVENTS_BY_PUBLISHERS_QUERY,
      {
        publishers,
        topics: topics?.length ? mqttTopicInputs(topics) : undefined,
        fromDatetime,
        toDatetime,
      },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    if (res.data?.getHistoricEventsByPublishers) {
      return res.data.getHistoricEventsByPublishers.map(graphqlHistoricalEventToHistoricEvent)
    }
    return []
  }

  public async getHistoricEventsByProperty(
    propertyKeys: string[],
    binaryOperator: BinaryOperator = 'OR',
    topics?: string[],
    fromDatetime?: string,
    toDatetime?: string,
  ): Promise<HistoricEvent[]> {
    const res = await this.executeQuery<{ getHistoricEventsByProperty: GraphqlHistoricalEvent[] }>(
      GET_HISTORIC_EVENTS_BY_PROPERTY_QUERY,
      {
        propertyKeys,
        binaryOperator,
        topics: topics?.length ? mqttTopicInputs(topics) : undefined,
        fromDatetime,
        toDatetime,
      },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    if (res.data?.getHistoricEventsByProperty) {
      return res.data.getHistoricEventsByProperty.map(graphqlHistoricalEventToHistoricEvent)
    }
    return []
  }

  public async getUnsNodesByProperty(
    propertyKeys: string[],
    topics?: string[],
    excludeTopics = false,
  ): Promise<UnsNode[]> {
    const res = await this.executeQuery<{ getUnsNodesByProperty: GraphqlUnsNode[] }>(
      GET_UNS_NODES_BY_PROPERTY_QUERY,
      {
        propertyKeys,
        topics: topics?.length ? mqttTopicInputs(topics) : undefined,
        excludeTopics,
      },
    )
    if (res.data?.getUnsNodesByProperty) {
      return res.data.getUnsNodesByProperty.map(graphqlUnsNodeToUnsNode)
    }
    return []
  }

  public async getSpbNodesByMetric(metricNames: string[]): Promise<SparkplugNode[]> {
    const res = await this.executeQuery<{ getSpbNodesByMetric: GraphqlSpbNode[] }>(
      GET_SPB_NODES_BY_METRIC_QUERY,
      { metricNames },
    )
    if (res.data?.getSpbNodesByMetric) {
      return res.data.getSpbNodesByMetric.map(graphqlSpbNodeToSparkplugNode)
    }
    return []
  }

  private sendMqttSubscription(
    registryId: string,
    topics: string[],
    onMessage: (msg: MqttMessage) => void,
  ): string | undefined {
    if (!this.wsProtocolReady || !this.wsConnected || this.ws?.readyState !== WebSocket.OPEN) {
      return undefined
    }

    const wsSubId = `sub_mqtt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    this.activeWsSubscriptions.set(wsSubId, (data: unknown) => {
      const payload = data as { getMqttMessages?: GraphqlMqttMessage }
      if (payload?.getMqttMessages) {
        onMessage(graphqlMqttMessageToMqttMessage(payload.getMqttMessages))
      }
    })

    this.ws.send(
      JSON.stringify({
        id: wsSubId,
        type: 'subscribe',
        payload: {
          query: SUBSCRIBE_MQTT_MESSAGES,
          variables: { topics: mqttTopicInputs(topics) },
        },
      }),
    )

    const entry = this.mqttMessageSubs.get(registryId)
    if (entry) {
      entry.wsSubId = wsSubId
    }

    return wsSubId
  }

  private resubscribeMqttMessages() {
    for (const [registryId, entry] of this.mqttMessageSubs.entries()) {
      if (entry.wsSubId) {
        this.activeWsSubscriptions.delete(entry.wsSubId)
        entry.wsSubId = undefined
      }
      this.sendMqttSubscription(registryId, entry.topics, entry.onMessage)
    }
  }

  public subscribeMqttMessages(topics: string[], onMessage: (msg: MqttMessage) => void): () => void {
    const registryId = `reg_mqtt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    this.mqttMessageSubs.set(registryId, { topics, onMessage })
    this.sendMqttSubscription(registryId, topics, onMessage)

    return () => {
      const entry = this.mqttMessageSubs.get(registryId)
      if (entry?.wsSubId) {
        this.activeWsSubscriptions.delete(entry.wsSubId)
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ id: entry.wsSubId, type: 'complete' }))
        }
      }
      this.mqttMessageSubs.delete(registryId)
    }
  }

  public subscribeKafkaMessages(topics: string[], onMessage: (msg: KafkaMessage) => void): () => void {
    if (this.wsConnected && this.ws?.readyState === WebSocket.OPEN) {
      const subId = `sub_kafka_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      this.activeWsSubscriptions.set(subId, (data: unknown) => {
        const payload = data as { getKafkaMessages?: GraphqlKafkaMessage }
        if (payload?.getKafkaMessages) {
          const message = payload.getKafkaMessages
          onMessage({
            id: `${message.topic}:${Date.now()}`,
            topic: message.topic,
            payload:
              message.payload?.data === undefined || message.payload?.data === null
                ? null
                : (typeof message.payload.data === 'object'
                    ? (message.payload.data as Record<string, unknown>)
                    : String(message.payload.data)),
            timestamp: new Date().toISOString(),
          })
        }
      })

      this.ws.send(
        JSON.stringify({
          id: subId,
          type: 'subscribe',
          payload: {
            query: SUBSCRIBE_KAFKA_MESSAGES,
            variables: { topics: topics.map((topic) => ({ topic })) },
          },
        }),
      )

      return () => {
        this.activeWsSubscriptions.delete(subId)
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ id: subId, type: 'complete' }))
        }
      }
    }

    return () => undefined
  }

  public getHealth(): SystemHealthInfo {
    return {
      status: this.isLiveBackend ? 'LIVE' : this.wsConnected ? 'DEGRADED' : 'DOWN',
      graphqlHttp: this.isLiveBackend,
      graphqlWs: this.wsProtocolReady,
      mqttBroker: this.isLiveBackend ? 'ONLINE' : 'OFFLINE',
      neo4jTree: this.isLiveBackend ? 'ONLINE' : 'OFFLINE',
      timescaleHistorian: this.isLiveBackend ? 'ONLINE' : 'OFFLINE',
      kafkaBroker: this.isLiveBackend ? 'ONLINE' : 'OFFLINE',
      sparkplugMapper: this.isLiveBackend ? 'ONLINE' : 'OFFLINE',
      lastPingMs: this.lastPingMs || 0,
      endpointUrl: this.httpUrl,
      mode: this.isLiveBackend ? 'LIVE_GRAPHQL' : 'SIMULATED_MOCK',
    }
  }

  public onHealthChange(cb: (health: SystemHealthInfo) => void): () => void {
    this.healthListeners.add(cb)
    cb(this.getHealth())
    return () => {
      this.healthListeners.delete(cb)
    }
  }

  private notifyHealth() {
    const health = this.getHealth()
    this.healthListeners.forEach((listener) => listener(health))
  }
}

export const unsGraphQLClient = new UnsGraphQLClient()
