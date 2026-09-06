export type GraphqlUnsNode = {
  nodeName: string
  nodeType: string
  namespace: string
  payload: { data: unknown } | null
  created: string
  lastUpdated: string
}

/**
 * `AssetNode` in the schema: a thing the Asset Model declares exists, as opposed to a
 * `GraphqlUnsNode`, which is a topic somebody published on.
 */
export type GraphqlAssetNode = {
  id?: number
  path: string
  segment: string
  level: string
  name: string
  description?: string | null
  manufacturer?: string | null
  modelNumber?: string | null
  serialNumber?: string | null
  criticality?: string | null
  isActive: boolean
  attributes?: { data: unknown } | null
}

/** One Asset root of an Access Group (`AccessGroupRootType`). */
export type AccessGroupRootDto = {
  assetId: number
  path: string
  segment: string
  level: string
}

/** A named Access Group: who may see which Asset subtree (`AccessGroupType`). */
export type AccessGroupDto = {
  id: number
  name: string
  roots: AccessGroupRootDto[]
  subjects: string[]
}

/** Minimal Asset row for the Access Group picker (`getAssets`). */
export type AccessAssetDto = {
  id: number
  path: string
  segment: string
  level: string
}

/** What the Asset Model says about one Metric Key: its name, and the unit it is in. */
export type GraphqlMetricDefinition = {
  metricKey: string
  displayName?: string | null
  unitOfMeasure?: string | null
  minValue?: number | null
  maxValue?: number | null
}

/** `TopicContextType`: the Enrichment for one topic. Null for an Unmodelled Topic. */
export type GraphqlTopicContext = {
  topic: string
  asset: GraphqlAssetNode
  metricPath: string
  enterprise?: string | null
  site?: string | null
  area?: string | null
  productionUnit?: string | null
  line?: string | null
  workCell?: string | null
  machine?: string | null
  metricDefinitions: GraphqlMetricDefinition[]
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
    | { __typename: 'JSONPayload'; json: unknown }
    | { __typename: 'BytesPayload'; bytes: string }
    | null
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

/** `AlertRuleType` in the schema. The roles are the enum spellings: ADMIN, OPERATOR, … */
export type GraphqlAlertRule = {
  id: string
  name: string
  description: string
  enabled: boolean
  severity: string
  category: string
  topic: string
  metricField: string
  condition: string
  thresholdValue: number | string | boolean
  thresholdUpperValue?: number | null
  unit?: string | null
  delaySeconds: number
  escalationRole?: string | null
  escalationTimeoutMinutes?: number | null
  notifyRoles: string[]
  autoResolveOnNormal: boolean
  inAppNotification: boolean
  audioChime: boolean
  mqttPublishOnTrigger: boolean
  mqttAlarmTopic?: string | null
  emailWebhook: boolean
  webhookUrl?: string | null
  triggerCount: number
  lastTriggeredAt?: string | null
  lastEvaluatedAt?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export type GraphqlSpbNode = {
  topic: string
  timestamp: string
  metrics: GraphqlSpbMetric[]
  seq: number
  uuid?: string | null
  body?: string | null
}

/** `HierarchyCellType` in the schema: a work cell (instance tag) and the machines under it. */
export type GraphqlHierarchyCell = {
  name: string
  machines: string[]
}

/** `HierarchyLineType` in the schema: a line and the cells (instance tags) under it. */
export type GraphqlHierarchyLine = {
  name: string
  cells: GraphqlHierarchyCell[]
}

/** `HierarchyAreaType` in the schema: an area in the ISA-95 tree. */
export type GraphqlHierarchyArea = {
  name: string
  kind: string
  lines: GraphqlHierarchyLine[]
}

/** `HierarchySiteType` in the schema: a site and the areas under it. */
export type GraphqlHierarchySite = {
  name: string
  areas: GraphqlHierarchyArea[]
}

/** `HierarchyTreeType` in the schema: the ISA-95 tree stored in settings.yaml. */
export type GraphqlHierarchyTree = {
  enterprise: string
  sites: GraphqlHierarchySite[]
}

/** `HierarchyMigrateJob`: one-at-a-time prefix migrate of historian topics and graph nodes. */
export type GraphqlHierarchyMigrateJob = {
  status: string
  oldPrefix?: string | null
  newPrefix?: string | null
  rewritten?: number | null
  error?: string | null
}

/** `HierarchySaveResult`: the tree as stored, plus the migrate job that save started or left idle. */
export type GraphqlHierarchySaveResult = {
  tree: GraphqlHierarchyTree
  job: GraphqlHierarchyMigrateJob
}

/** `HierarchyLineInput` in the schema. */
export type GraphqlHierarchyLineInput = {
  name: string
  cells: GraphqlHierarchyCell[]
}

/** `HierarchyAreaInput` in the schema. `kind` defaults to production when omitted. */
export type GraphqlHierarchyAreaInput = {
  name: string
  kind?: string | null
  lines: GraphqlHierarchyLineInput[]
}

/** `HierarchySiteInput` in the schema. */
export type GraphqlHierarchySiteInput = {
  name: string
  areas: GraphqlHierarchyAreaInput[]
}

/** `HierarchyTreeInput` in the schema: the ISA-95 tree to persist in settings.yaml. */
export type GraphqlHierarchyTreeInput = {
  enterprise: string
  sites: GraphqlHierarchySiteInput[]
}

/** `PrefixRenameInput`: a topic-prefix rename the console recorded while editing. */
export type GraphqlPrefixRenameInput = {
  oldPrefix: string
  newPrefix: string
}

/** `ConnectivityProtocol` enum on the server. Only OPC_UA is in this slice. */
export type GraphqlConnectivityProtocol = 'OPC_UA'
export type GraphqlConnectivityAuthMode = 'ANONYMOUS' | 'USERNAME' | 'X509'
export type GraphqlConnectivitySecurityPolicy =
  | 'NONE'
  | 'BASIC256_SHA256'
  | 'AES128_SHA256_RSA_OAEP'
  | 'AES256_SHA256_RSA_PSS'
export type GraphqlConnectivitySecurityMode = 'NONE' | 'SIGN' | 'SIGN_AND_ENCRYPT'

/** `SignalSemanticClass` enum on the server. */
export type GraphqlSignalSemanticClass =
  | 'MeasuredValue'
  | 'EnergyConsumption'
  | 'CounterOK'
  | 'CounterNOK'
  | 'State'

/** `SignalDataType` enum on the server. */
export type GraphqlSignalDataType = 'Double' | 'Boolean' | 'Integer' | 'String'

/** `UnitOfMeasureType`: one row in the Unit of Measure catalog. */
export type GraphqlUnitOfMeasure = {
  symbol: string
  name?: string | null
}

/** `ConnectivityServerType`: an OPC UA server the console dials, with its subscribed tags. */
export type GraphqlConnectivityTag = {
  serverId: string
  nodeId: string
  browsePath: string
  displayName: string
  mqttTopic: string
  subscribed: boolean
  createdAt?: string | null
  updatedAt?: string | null
  assetId?: number | null
  assetPath?: string | null
  assetDisplayName?: string | null
  unitOfMeasure?: string | null
  semanticClass?: GraphqlSignalSemanticClass | null
  dataType?: GraphqlSignalDataType | null
  labels?: string[]
}

/** `SubscribedSignalType`: a subscribed catalog tag, named by the server it belongs to. */
export type GraphqlSubscribedSignal = GraphqlConnectivityTag & {
  serverName: string
}

/** `ConnectivityTagUpdateInput`: partial update for engineer-authored signal context. */
export type GraphqlConnectivityTagPatch = {
  displayName?: string
  mqttTopic?: string
  assetId?: number | null
  unitOfMeasure?: string | null
  semanticClass?: GraphqlSignalSemanticClass | null
  dataType?: GraphqlSignalDataType | null
  labels?: string[]
}

export type GraphqlConnectivityServer = {
  id: string
  name: string
  protocol: GraphqlConnectivityProtocol
  endpoint: string
  authMode?: GraphqlConnectivityAuthMode
  username?: string
  hasPassword?: boolean
  securityPolicy?: GraphqlConnectivitySecurityPolicy
  securityMode?: GraphqlConnectivitySecurityMode
  certificate?: string
  hasPrivateKey?: boolean
  serverCertificate?: string
  lastStatus: string
  lastError: string
  lastTestedAt?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  tags: GraphqlConnectivityTag[]
}

/** `ConnectivityServerInput`: the id is supplied by the console. Password is write-only. */
export type GraphqlConnectivityServerInput = {
  id: string
  name: string
  protocol: GraphqlConnectivityProtocol
  endpoint: string
  authMode?: GraphqlConnectivityAuthMode
  securityPolicy?: GraphqlConnectivitySecurityPolicy
  securityMode?: GraphqlConnectivitySecurityMode
  username?: string
  password?: string
  certificate?: string
  privateKey?: string
  serverCertificate?: string
}

/** `ConnectivityTestResultType`: the outcome of a probe against one OPC UA endpoint. */
export type GraphqlConnectivityTestResult = {
  ok: boolean
  error: string | null
  elapsedMs: number
}

/** `OpcUaBrowseNodeType`: an OPC UA node the console browsed or discovered. */
export type GraphqlOpcUaBrowseNode = {
  nodeId: string
  browseName: string
  displayName: string
  browsePath: string
  nodeClass: string
  hasChildren: boolean
}

/** `OpcUaDataValueType`: one OPC UA node's current value as read from the server. */
export type GraphqlOpcUaDataValue = {
  nodeId: string
  displayName: string
  browsePath: string
  value: unknown
  dataType: string | null
  sourceTimestamp: string | null
  serverTimestamp: string | null
  status: string
}
