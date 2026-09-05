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
  syntheticParameterGroupNodes,
  syntheticSensorNodes,
} from '../../lib/uns/isa95-probe'
import {
  assetToUnsNode,
  metricChildNodes,
  topicContextProperties,
} from '../../lib/uns/map-assets'
import type {
  HistoricEvent,
  KafkaMessage,
  MqttMessage,
  SparkplugNode,
  SystemHealthInfo,
  UnsNode,
} from '../../types/uns'
import {
  DELETE_ALERT_RULE_MUTATION,
  GET_ALERT_RULES_QUERY,
  GET_ASSET_CHILDREN_QUERY,
  GET_CONNECTIVITY_SERVERS_QUERY,
  GET_HIERARCHY_QUERY,
  GET_HISTORIC_EVENTS_BY_PROPERTY_QUERY,
  GET_HISTORIC_EVENTS_BY_PUBLISHERS_QUERY,
  GET_HISTORIC_EVENTS_IN_TIME_RANGE_QUERY,
  GET_SPB_NODES_BY_METRIC_QUERY,
  GET_TOPIC_CONTEXT_QUERY,
  GET_UNS_NODES_BY_PROPERTY_QUERY,
  GET_UNS_NODES_QUERY,
  GET_UNS_TREE_CHILDREN_QUERY,
  READ_OPCUA_NODES_QUERY,
  RECORD_ALERT_RULE_EVALUATION_MUTATION,
  RETRY_HIERARCHY_MIGRATE_MUTATION,
  SAVE_ALERT_RULES_MUTATION,
  SAVE_ALERT_RULE_MUTATION,
  SAVE_CONNECTIVITY_SERVER_MUTATION,
  SAVE_HIERARCHY_MUTATION,
  SET_ALERT_RULE_ENABLED_MUTATION,
  SUBSCRIBE_KAFKA_MESSAGES,
  SUBSCRIBE_MQTT_MESSAGES,
  SUBSCRIBE_OPCUA_DATA_CHANGES,
  SUBSCRIBE_OPCUA_VARIABLES_MUTATION,
  BROWSE_OPCUA_QUERY,
  DELETE_ACCESS_GROUP_MUTATION,
  DELETE_CONNECTIVITY_SERVER_MUTATION,
  DISCOVER_OPCUA_VARIABLES_QUERY,
  GET_ACCESS_GROUPS_QUERY,
  GET_ASSETS_QUERY,
  SAVE_ACCESS_GROUP_MUTATION,
  SET_ACCESS_GROUP_MEMBERS_MUTATION,
  TEST_OPCUA_CONNECTION_QUERY,
  UNSUBSCRIBE_CONNECTIVITY_TAG_MUTATION,
  UPDATE_CONNECTIVITY_TAG_TOPIC_MUTATION,
} from './queries'
import {
  alertRuleToGraphqlInput,
  graphqlAlertRuleToAlertRule,
} from '../../lib/alarms/map-alert-rules'
import type { AlertRule } from '../../types/alarm'
import type {
  AccessAssetDto,
  AccessGroupDto,
  GraphqlAlertRule,
  GraphqlAssetNode,
  GraphqlConnectivityServer,
  GraphqlConnectivityServerInput,
  GraphqlConnectivityTestResult,
  GraphqlHistoricalEvent,
  GraphqlHierarchyMigrateJob,
  GraphqlHierarchySaveResult,
  GraphqlHierarchyTree,
  GraphqlHierarchyTreeInput,
  GraphqlKafkaMessage,
  GraphqlMqttMessage,
  GraphqlOpcUaBrowseNode,
  GraphqlOpcUaDataValue,
  GraphqlPrefixRenameInput,
  GraphqlSpbNode,
  GraphqlTopicContext,
  GraphqlUnsNode,
} from './types'
import { authClient } from '../../lib/auth/oidc'

/**
 * How this client gets a token. Injected so the tests never construct a real UserManager,
 * and read per request rather than captured, so a silent renew takes effect immediately.
 */
export interface AuthHooks {
  token(): string | null
  refresh(): Promise<string | null>
  /** Called when a refreshed token is still refused. Sends the user back to the realm. */
  onExpired(): void
}

const defaultAuthHooks: AuthHooks = {
  token: () => authClient.accessToken(),
  refresh: () => authClient.refresh(),
  onExpired: () => { void authClient.signIn() },
}

function asInt(value: number | string): number {
  return typeof value === 'number' ? value : Number(value)
}

function mapAccessGroup(group: AccessGroupDto): AccessGroupDto {
  return {
    id: asInt(group.id),
    name: group.name,
    subjects: [...group.subjects],
    roots: group.roots.map((root) => ({
      assetId: asInt(root.assetId),
      path: root.path,
      segment: root.segment,
      level: root.level,
    })),
  }
}

type BinaryOperator = 'OR' | 'AND' | 'NOT'

export class UnsGraphQLClient {
  private httpUrl: string
  private wsUrl: string
  private auth: AuthHooks
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

  constructor(httpUrl = '/graphql', wsUrl?: string, auth: AuthHooks = defaultAuthHooks) {
    this.auth = auth
    this.httpUrl = httpUrl
    this.wsUrl =
      wsUrl ||
      (typeof window !== 'undefined'
        ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/graphql`
        : 'ws://localhost:8000/graphql')
    this.initWebSocket()
  }

  /** Tear down and reopen the subscription socket — e.g. after sign-in grants a token. */
  public reconnect() {
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
      // Capture at open, not at close: a token that arrives while this anonymous socket is
      // being refused must not look like an expired session and restart the OIDC redirect.
      const openedWithToken = this.auth.token() !== null

      this.ws.onopen = () => {
        this.wsConnected = true
        this.wsProtocolReady = false
        const token = this.auth.token()
        // graphql-transport-ws puts credentials here because a browser cannot set a header on
        // a handshake. AuthenticatedGraphQLRouter.on_ws_connect reads exactly this key.
        this.ws?.send(
          JSON.stringify({
            type: 'connection_init',
            payload: token ? { Authorization: `Bearer ${token}` } : {},
          }),
        )
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

      this.ws.onclose = (event) => {
        this.wsConnected = false
        this.wsProtocolReady = false
        if (event.code === 4403 && openedWithToken) {
          // The realm refused a socket that presented a token. An anonymous visitor on the
          // landing page is not an expired session; signing them in here races the OIDC
          // callback into a redirect loop.
          this.auth.onExpired()
        }
        this.notifyHealth()
      }
    } catch {
      this.wsConnected = false
    }
  }

  private authHeaders(): Record<string, string> {
    const token = this.auth.token()
    // Absent rather than `Bearer `: an empty bearer is a malformed header the server logs as
    // a bad token instead of as an anonymous request.
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  private async executeQuery<T>(
    query: string,
    variables: Record<string, unknown> = {},
    retryOnUnauthorized = true,
  ): Promise<{ data: T | null; error?: string }> {
    const t0 = performance.now()
    try {
      const hadToken = this.auth.token() !== null
      const response = await fetch(this.httpUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...this.authHeaders(),
        },
        body: JSON.stringify({ query, variables }),
      })

      this.lastPingMs = Math.round(performance.now() - t0)

      if (response.status === 401) {
        // One refresh, then the realm. Never a loop: a 401 that survives a fresh token is a
        // permission or configuration problem, and retrying it forever hides that.
        if (retryOnUnauthorized && hadToken && (await this.auth.refresh()) !== null) {
          return this.executeQuery<T>(query, variables, false)
        }
        if (!hadToken) {
          // The landing page and the OIDC callback both mount providers that query GraphQL
          // before a token exists. Sending that visitor to the realm races completeRedirect.
          return { data: null, error: 'This endpoint requires a bearer token from the UNS realm.' }
        }
        this.auth.onExpired()
        // An expired session is not an empty result. Every caller of this method turns
        // `{data: null}` into `[]`, and an operator reads an empty plant tree as a quiet
        // plant rather than as a session that ended.
        return { data: null, error: 'Your session has expired. Signing in again.' }
      }

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
   * The roots of the tree: the Asset Model's, or the graph database's when nothing has
   * been modelled yet.
   *
   * An empty Asset Model is a platform that has been deployed but not yet described,
   * and it must still show the traffic it is receiving.
   */
  public async getUnsRootNodes(): Promise<UnsNode[]> {
    const roots = await this.getAssetChildren(null)
    if (roots.length > 0) {
      return roots.map(assetToUnsNode)
    }
    return this.getUnsNodes([childrenTopic('')])
  }

  /**
   * Children of a node, from the Asset Model where it reaches and from what was
   * published where it does not.
   *
   * The order is the point: what an engineer declared beats what a wildcard query
   * happens to find, and both beat the ISA-95 guesses that are only still here so that
   * an unmodelled simulator install keeps working.
   */
  public async getUnsNodeChildren(parentTopic: string): Promise<UnsNode[]> {
    const modelled = await this.getModelledChildren(parentTopic)
    if (modelled.length > 0) {
      return modelled
    }

    const depth = topicDepth(parentTopic)

    if (isParameterGroupTopic(parentTopic)) {
      return syntheticSensorNodes(parentTopic)
    }

    if (depth >= 6) {
      return syntheticParameterGroupNodes(parentTopic)
    }

    const direct = await this.getUnsNodes([childrenTopic(parentTopic)])
    if (direct.length > 0) {
      return direct
    }

    if (depth >= 5) {
      return syntheticParameterGroupNodes(parentTopic)
    }

    return []
  }

  private async getAssetChildren(path: string | null): Promise<GraphqlAssetNode[]> {
    const res = await this.executeQuery<{ getAssetChildren: GraphqlAssetNode[] }>(
      GET_ASSET_CHILDREN_QUERY,
      { path },
    )
    return res.data?.getAssetChildren ?? []
  }

  /**
   * What the Asset Model declares below a topic: Assets if the hierarchy continues,
   * otherwise the Metric segments of the Asset that publishes it.
   */
  private async getModelledChildren(parentTopic: string): Promise<UnsNode[]> {
    const res = await this.executeQuery<{
      getAssetChildren: GraphqlAssetNode[]
      getTopicContext: GraphqlTopicContext | null
    }>(GET_UNS_TREE_CHILDREN_QUERY, { topic: parentTopic })

    const assets = res.data?.getAssetChildren ?? []
    if (assets.length > 0) {
      return assets.map(assetToUnsNode)
    }
    return metricChildNodes(parentTopic, res.data?.getTopicContext ?? null)
  }

  /**
   * Read-time Enrichment for one topic: which Line and Machine it belongs to, and the
   * unit its numbers are in, as properties ready to show beside a live payload.
   *
   * Empty for an Unmodelled Topic — the console shows the payload either way, because
   * a value with no context is still a value.
   */
  public async getTopicEnrichment(topic: string): Promise<Record<string, string>> {
    const res = await this.executeQuery<{ getTopicContext: GraphqlTopicContext | null }>(
      GET_TOPIC_CONTEXT_QUERY,
      { topic },
    )
    return res.data?.getTopicContext ? topicContextProperties(res.data.getTopicContext) : {}
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

  /**
   * The Alert Rules stored in Postgres, or null when the server cannot be reached.
   *
   * Null and empty mean different things and must stay distinguishable: an empty
   * list is a platform with no rules configured, while null is "we do not know",
   * and treating the second as the first is how a console silently disarms every
   * alarm an operator configured.
   */
  public async getAlertRules(): Promise<AlertRule[] | null> {
    const res = await this.executeQuery<{ getAlertRules: GraphqlAlertRule[] }>(
      GET_ALERT_RULES_QUERY,
    )
    if (res.error || !res.data?.getAlertRules) {
      return null
    }
    return res.data.getAlertRules.map(graphqlAlertRuleToAlertRule)
  }

  public async saveAlertRule(rule: AlertRule): Promise<AlertRule> {
    const res = await this.executeQuery<{ saveAlertRule: GraphqlAlertRule }>(
      SAVE_ALERT_RULE_MUTATION,
      { rule: alertRuleToGraphqlInput(rule) },
    )
    if (res.error || !res.data?.saveAlertRule) {
      throw new Error(res.error || 'Alert Rule was not saved')
    }
    return graphqlAlertRuleToAlertRule(res.data.saveAlertRule)
  }

  /** Used once, to hand over the rules a browser had kept to itself. */
  public async saveAlertRules(rules: AlertRule[]): Promise<AlertRule[]> {
    const res = await this.executeQuery<{ saveAlertRules: GraphqlAlertRule[] }>(
      SAVE_ALERT_RULES_MUTATION,
      { rules: rules.map(alertRuleToGraphqlInput) },
    )
    if (res.error || !res.data?.saveAlertRules) {
      throw new Error(res.error || 'Alert Rules were not imported')
    }
    return res.data.saveAlertRules.map(graphqlAlertRuleToAlertRule)
  }

  public async deleteAlertRule(id: string): Promise<boolean> {
    const res = await this.executeQuery<{ deleteAlertRule: boolean }>(
      DELETE_ALERT_RULE_MUTATION,
      { id },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.deleteAlertRule === true
  }

  public async setAlertRuleEnabled(id: string, enabled: boolean): Promise<AlertRule | null> {
    const res = await this.executeQuery<{ setAlertRuleEnabled: GraphqlAlertRule | null }>(
      SET_ALERT_RULE_ENABLED_MUTATION,
      { id, enabled },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.setAlertRuleEnabled
      ? graphqlAlertRuleToAlertRule(res.data.setAlertRuleEnabled)
      : null
  }

  /**
   * Report that a rule was evaluated. Fire-and-forget on purpose: the alarm has
   * already been raised in the UI, and losing a counter must not block it.
   */
  public async recordAlertRuleEvaluation(id: string, triggered: boolean): Promise<void> {
    await this.executeQuery(RECORD_ALERT_RULE_EVALUATION_MUTATION, { id, triggered })
  }

  /**
   * The plant hierarchy stored in plant.yaml. Null when the server cannot be reached,
   * because a console that silently renders an empty tree hides a deployment problem.
   */
  public async getHierarchy(): Promise<GraphqlHierarchyTree | null> {
    const res = await this.executeQuery<{ getHierarchy: GraphqlHierarchyTree }>(GET_HIERARCHY_QUERY)
    if (res.error || !res.data?.getHierarchy) {
      return null
    }
    return res.data.getHierarchy
  }

  /**
   * Persist the whole ISA-95 tree at once and start a prefix-migrate job for any
   * renames. The console edits locally and saves once: there is no safe meaning to
   * "rename one site without saying what the rest of the plant now is".
   */
  public async saveHierarchy(
    tree: GraphqlHierarchyTreeInput,
    renames: GraphqlPrefixRenameInput[],
  ): Promise<GraphqlHierarchySaveResult> {
    const res = await this.executeQuery<{ saveHierarchy: GraphqlHierarchySaveResult }>(
      SAVE_HIERARCHY_MUTATION,
      { tree, renames },
    )
    if (res.error || !res.data?.saveHierarchy) {
      throw new Error(res.error || 'Hierarchy was not saved')
    }
    return res.data.saveHierarchy
  }

  /** Re-run a failed prefix-migrate job. Throws when the server is unreachable. */
  public async retryHierarchyMigrate(): Promise<GraphqlHierarchyMigrateJob> {
    const res = await this.executeQuery<{ retryHierarchyMigrate: GraphqlHierarchyMigrateJob }>(
      RETRY_HIERARCHY_MIGRATE_MUTATION,
    )
    if (res.error || !res.data?.retryHierarchyMigrate) {
      throw new Error(res.error || 'Hierarchy migrate retry failed')
    }
    return res.data.retryHierarchyMigrate
  }

  public async getAccessGroups(): Promise<AccessGroupDto[]> {
    const res = await this.executeQuery<{ getAccessGroups: AccessGroupDto[] }>(GET_ACCESS_GROUPS_QUERY)
    return (res.data?.getAccessGroups ?? []).map(mapAccessGroup)
  }

  public async saveAccessGroup(
    name: string,
    rootAssetIds: number[],
    id?: number | null,
  ): Promise<AccessGroupDto> {
    const res = await this.executeQuery<{ saveAccessGroup: AccessGroupDto }>(SAVE_ACCESS_GROUP_MUTATION, {
      name,
      rootAssetIds,
      id: id ?? null,
    })
    if (res.error || !res.data?.saveAccessGroup) {
      throw new Error(res.error || 'Access Group was not saved')
    }
    return mapAccessGroup(res.data.saveAccessGroup)
  }

  public async deleteAccessGroup(id: number): Promise<boolean> {
    const res = await this.executeQuery<{ deleteAccessGroup: boolean }>(DELETE_ACCESS_GROUP_MUTATION, { id })
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.deleteAccessGroup === true
  }

  public async setAccessGroupMembers(id: number, subjects: string[]): Promise<AccessGroupDto> {
    const res = await this.executeQuery<{ setAccessGroupMembers: AccessGroupDto }>(
      SET_ACCESS_GROUP_MEMBERS_MUTATION,
      { id, subjects },
    )
    if (res.error || !res.data?.setAccessGroupMembers) {
      throw new Error(res.error || 'Access Group members were not updated')
    }
    return mapAccessGroup(res.data.setAccessGroupMembers)
  }

  /**
   * Flat Asset Model list for the Access Group picker, ordered by the server (path).
   * Empty when the endpoint cannot be reached.
   */
  public async getAssets(): Promise<AccessAssetDto[]> {
    const res = await this.executeQuery<{ getAssets: AccessAssetDto[] }>(GET_ASSETS_QUERY)
    return (res.data?.getAssets ?? []).map((asset) => ({
      id: asInt(asset.id),
      path: asset.path,
      segment: asset.segment,
      level: asset.level,
    }))
  }

  /**
   * Assets & Connectivity (ADR-0008). Servers and tags live in `console.connectivity_*`;
   * the console edits them only through GraphQL, and `opcua_client` polls the catalog.
   * Null means the endpoint could not be reached, not that the platform has no servers.
   */
  public async getConnectivityServers(
    protocol?: 'OPC_UA',
  ): Promise<GraphqlConnectivityServer[] | null> {
    const res = await this.executeQuery<{ getConnectivityServers: GraphqlConnectivityServer[] }>(
      GET_CONNECTIVITY_SERVERS_QUERY,
      protocol ? { protocol } : {},
    )
    if (res.error) {
      return null
    }
    return res.data?.getConnectivityServers ?? []
  }

  public async saveConnectivityServer(
    server: GraphqlConnectivityServerInput,
  ): Promise<GraphqlConnectivityServer> {
    const res = await this.executeQuery<{ saveConnectivityServer: GraphqlConnectivityServer }>(
      SAVE_CONNECTIVITY_SERVER_MUTATION,
      { server },
    )
    if (res.error || !res.data?.saveConnectivityServer) {
      throw new Error(res.error || 'Connectivity server was not saved')
    }
    return res.data.saveConnectivityServer
  }

  public async deleteConnectivityServer(id: string): Promise<boolean> {
    const res = await this.executeQuery<{ deleteConnectivityServer: boolean }>(
      DELETE_CONNECTIVITY_SERVER_MUTATION,
      { id },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.deleteConnectivityServer === true
  }

  public async testOpcUaConnection(endpoint: string): Promise<GraphqlConnectivityTestResult> {
    const res = await this.executeQuery<{ testOpcUaConnection: GraphqlConnectivityTestResult }>(
      TEST_OPCUA_CONNECTION_QUERY,
      { endpoint },
    )
    if (res.error || !res.data?.testOpcUaConnection) {
      return { ok: false, error: res.error ?? 'unreachable', elapsedMs: 0 }
    }
    return res.data.testOpcUaConnection
  }

  public async browseOpcUa(
    endpoint: string,
    nodeId?: string | null,
  ): Promise<GraphqlOpcUaBrowseNode[]> {
    const res = await this.executeQuery<{ browseOpcUa: GraphqlOpcUaBrowseNode[] }>(
      BROWSE_OPCUA_QUERY,
      { endpoint, nodeId: nodeId ?? null },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.browseOpcUa ?? []
  }

  public async discoverOpcUaVariables(
    endpoint: string,
    nodeId?: string | null,
  ): Promise<GraphqlOpcUaBrowseNode[]> {
    const res = await this.executeQuery<{ discoverOpcUaVariables: GraphqlOpcUaBrowseNode[] }>(
      DISCOVER_OPCUA_VARIABLES_QUERY,
      { endpoint, nodeId: nodeId ?? null },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.discoverOpcUaVariables ?? []
  }

  public async subscribeOpcUaVariables(
    serverId: string,
    nodeId?: string | null,
  ): Promise<{ nodeId: string; browsePath: string; displayName: string; mqttTopic: string; subscribed: boolean }[]> {
    const res = await this.executeQuery<{ subscribeOpcUaVariables: unknown[] }>(
      SUBSCRIBE_OPCUA_VARIABLES_MUTATION,
      { serverId, nodeId: nodeId ?? null },
    )
    if (res.error || !res.data?.subscribeOpcUaVariables) {
      throw new Error(res.error || 'Subscribe failed')
    }
    return res.data.subscribeOpcUaVariables as never
  }

  public async updateConnectivityTagTopic(
    serverId: string,
    nodeId: string,
    mqttTopic: string,
  ): Promise<{ nodeId: string; mqttTopic: string; subscribed: boolean }> {
    const res = await this.executeQuery<{ updateConnectivityTagTopic: unknown }>(
      UPDATE_CONNECTIVITY_TAG_TOPIC_MUTATION,
      { serverId, nodeId, mqttTopic },
    )
    if (res.error || !res.data?.updateConnectivityTagTopic) {
      throw new Error(res.error || 'Topic was not updated')
    }
    return res.data.updateConnectivityTagTopic as never
  }

  public async unsubscribeConnectivityTag(serverId: string, nodeId: string): Promise<boolean> {
    const res = await this.executeQuery<{ unsubscribeConnectivityTag: boolean }>(
      UNSUBSCRIBE_CONNECTIVITY_TAG_MUTATION,
      { serverId, nodeId },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.unsubscribeConnectivityTag === true
  }

  /** One-shot read of current OPC UA node values; the drawer polls this before subscribing. */
  public async readOpcUaNodes(endpoint: string, nodeIds: string[]): Promise<GraphqlOpcUaDataValue[]> {
    const res = await this.executeQuery<{ readOpcUaNodes: GraphqlOpcUaDataValue[] }>(
      READ_OPCUA_NODES_QUERY,
      { endpoint, nodeIds },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.readOpcUaNodes ?? []
  }

  /**
   * Live OPC UA values over the graphql-transport-ws subscription. Returns an unsubscribe
   * function. When the socket is not ready, the caller falls back to polling
   * `readOpcUaNodes`; the server-side subscription exists either way.
   */
  public subscribeOpcUaDataChanges(
    endpoint: string,
    nodeIds: string[],
    onData: (value: GraphqlOpcUaDataValue) => void,
  ): () => void {
    if (!this.wsConnected || !this.wsProtocolReady || this.ws?.readyState !== WebSocket.OPEN) {
      return () => undefined
    }

    const subId = `sub_opcua_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    this.activeWsSubscriptions.set(subId, (data: unknown) => {
      const payload = data as { opcUaDataChanges?: GraphqlOpcUaDataValue }
      if (payload?.opcUaDataChanges) {
        onData(payload.opcUaDataChanges)
      }
    })

    this.ws.send(
      JSON.stringify({
        id: subId,
        type: 'subscribe',
        payload: {
          query: SUBSCRIBE_OPCUA_DATA_CHANGES,
          variables: { endpoint, nodeIds },
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

// A socket opened before sign-in was rejected with 4403; reconnect when a session appears.
if (typeof window !== 'undefined') {
  authClient.onSession((session) => {
    if (session) {
      unsGraphQLClient.reconnect()
    }
  })
}
