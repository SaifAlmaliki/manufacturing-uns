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

/** `HierarchyLineType` in the schema: a line and the cells (instance tags) under it. */
export type GraphqlHierarchyLine = {
  name: string
  cells: string[]
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

/** `HierarchyTreeType` in the schema: the ISA-95 tree stored in plant.yaml. */
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
  cells: string[]
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

/** `HierarchyTreeInput` in the schema: the ISA-95 tree to persist as plant.yaml. */
export type GraphqlHierarchyTreeInput = {
  enterprise: string
  sites: GraphqlHierarchySiteInput[]
}

/** `PrefixRenameInput`: a topic-prefix rename the console recorded while editing. */
export type GraphqlPrefixRenameInput = {
  oldPrefix: string
  newPrefix: string
}
