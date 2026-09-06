/**
 * GraphQL documents matching 07_uns_graphql/schema/uns_schema.graphql
 */

export const GET_UNS_NODES_QUERY = `
  query GetUnsNodes($topics: [MQTTTopicInput!]!) {
    getUnsNodes(topics: $topics) {
      nodeName
      nodeType
      namespace
      payload {
        data
      }
      created
      lastUpdated
    }
  }
`

/**
 * The Asset Model in Postgres is where the plant hierarchy is authored, so the tree
 * asks it before it asks the graph database (ADR-0003).
 */
const ASSET_FIELDS = `
  path
  segment
  level
  name
  description
  manufacturer
  modelNumber
  serialNumber
  criticality
  isActive
  attributes {
    data
  }
`

const METRIC_DEFINITION_FIELDS = `
  metricKey
  displayName
  unitOfMeasure
  minValue
  maxValue
`

export const GET_ASSET_CHILDREN_QUERY = `
  query GetAssetChildren($path: String) {
    getAssetChildren(path: $path) {
      ${ASSET_FIELDS}
    }
  }
`

/**
 * One request, both halves of an expansion: the Assets declared under this topic and,
 * for the branch below the deepest Asset, the Metric Definitions that describe it.
 * Two round trips per node expansion would be felt on a tree; one is not.
 */
export const GET_UNS_TREE_CHILDREN_QUERY = `
  query GetUnsTreeChildren($topic: String!) {
    getAssetChildren(path: $topic) {
      ${ASSET_FIELDS}
    }
    getTopicContext(topic: $topic) {
      topic
      metricPath
      metricDefinitions {
        ${METRIC_DEFINITION_FIELDS}
      }
      asset {
        ${ASSET_FIELDS}
      }
      enterprise
      site
      area
      productionUnit
      line
      workCell
      machine
    }
  }
`

export const GET_TOPIC_CONTEXT_QUERY = `
  query GetTopicContext($topic: String!) {
    getTopicContext(topic: $topic) {
      topic
      metricPath
      metricDefinitions {
        ${METRIC_DEFINITION_FIELDS}
      }
      asset {
        ${ASSET_FIELDS}
      }
      enterprise
      site
      area
      productionUnit
      line
      workCell
      machine
    }
  }
`

export const GET_HISTORIC_EVENTS_IN_TIME_RANGE_QUERY = `
  query GetHistoricEventsInTimeRange(
    $topics: [MQTTTopicInput!]!
    $fromDatetime: DateTime
    $toDatetime: DateTime
  ) {
    getHistoricEventsInTimeRange(
      topics: $topics
      fromDatetime: $fromDatetime
      toDatetime: $toDatetime
    ) {
      publisher
      timestamp
      topic
      payload {
        data
      }
    }
  }
`

export const GET_HISTORIC_EVENTS_BY_PUBLISHERS_QUERY = `
  query GetHistoricEventsByPublishers(
    $publishers: [String!]!
    $topics: [MQTTTopicInput!]
    $fromDatetime: DateTime
    $toDatetime: DateTime
  ) {
    getHistoricEventsByPublishers(
      publishers: $publishers
      topics: $topics
      fromDatetime: $fromDatetime
      toDatetime: $toDatetime
    ) {
      publisher
      timestamp
      topic
      payload {
        data
      }
    }
  }
`

export const GET_HISTORIC_EVENTS_BY_PROPERTY_QUERY = `
  query GetHistoricEventsByProperty(
    $propertyKeys: [String!]!
    $binaryOperator: BinaryOperator
    $topics: [MQTTTopicInput!]
    $fromDatetime: DateTime
    $toDatetime: DateTime
  ) {
    getHistoricEventsByProperty(
      propertyKeys: $propertyKeys
      binaryOperator: $binaryOperator
      topics: $topics
      fromDatetime: $fromDatetime
      toDatetime: $toDatetime
    ) {
      publisher
      timestamp
      topic
      payload {
        data
      }
    }
  }
`

export const GET_UNS_NODES_BY_PROPERTY_QUERY = `
  query GetUnsNodesByProperty(
    $propertyKeys: [String!]!
    $topics: [MQTTTopicInput!]
    $excludeTopics: Boolean
  ) {
    getUnsNodesByProperty(
      propertyKeys: $propertyKeys
      topics: $topics
      excludeTopics: $excludeTopics
    ) {
      nodeName
      nodeType
      namespace
      payload {
        data
      }
      created
      lastUpdated
    }
  }
`

export const GET_SPB_NODES_BY_METRIC_QUERY = `
  query GetSpbNodesByMetric($metricNames: [String!]!) {
    getSpbNodesByMetric(metricNames: $metricNames) {
      topic
      timestamp
      seq
      uuid
      body
      metrics {
        name
        alias
        timestamp
        datatype
        isHistorical
        isTransient
        isNull
        value {
          __typename
          ... on SPBPrimitive {
            data
          }
          ... on BytesPayload {
            data
          }
        }
      }
    }
  }
`

/**
 * Alert Rules live in Postgres schema `console`, not in this browser. Every document
 * below asks for the same field set, because a rule that renders with half its
 * settings is worse than one that fails to load.
 */
const ALERT_RULE_FIELDS = `
  id
  name
  description
  enabled
  severity
  category
  topic
  metricField
  condition
  thresholdValue
  thresholdUpperValue
  unit
  delaySeconds
  escalationRole
  escalationTimeoutMinutes
  notifyRoles
  autoResolveOnNormal
  inAppNotification
  audioChime
  mqttPublishOnTrigger
  mqttAlarmTopic
  emailWebhook
  webhookUrl
  triggerCount
  lastTriggeredAt
  lastEvaluatedAt
  createdAt
  updatedAt
`

export const GET_ALERT_RULES_QUERY = `
  query GetAlertRules {
    getAlertRules {
      ${ALERT_RULE_FIELDS}
    }
  }
`

export const SAVE_ALERT_RULE_MUTATION = `
  mutation SaveAlertRule($rule: AlertRuleInput!) {
    saveAlertRule(rule: $rule) {
      ${ALERT_RULE_FIELDS}
    }
  }
`

export const SAVE_ALERT_RULES_MUTATION = `
  mutation SaveAlertRules($rules: [AlertRuleInput!]!) {
    saveAlertRules(rules: $rules) {
      ${ALERT_RULE_FIELDS}
    }
  }
`

export const DELETE_ALERT_RULE_MUTATION = `
  mutation DeleteAlertRule($id: String!) {
    deleteAlertRule(id: $id)
  }
`

export const SET_ALERT_RULE_ENABLED_MUTATION = `
  mutation SetAlertRuleEnabled($id: String!, $enabled: Boolean!) {
    setAlertRuleEnabled(id: $id, enabled: $enabled) {
      ${ALERT_RULE_FIELDS}
    }
  }
`

export const RECORD_ALERT_RULE_EVALUATION_MUTATION = `
  mutation RecordAlertRuleEvaluation($id: String!, $triggered: Boolean!) {
    recordAlertRuleEvaluation(id: $id, triggered: $triggered) {
      id
      triggerCount
      lastTriggeredAt
      lastEvaluatedAt
    }
  }
`

export const SUBSCRIBE_MQTT_MESSAGES = `
  subscription GetMqttMessages($topics: [MQTTTopicInput!]!) {
    getMqttMessages(topics: $topics) {
      topic
      payload {
        __typename
        ... on JSONPayload {
          json: data
        }
        ... on BytesPayload {
          bytes: data
        }
      }
    }
  }
`

export const SUBSCRIBE_KAFKA_MESSAGES = `
  subscription GetKafkaMessages($topics: [String!]!) {
    getKafkaMessages(topics: $topics) {
      topic
      payload {
        data
      }
    }
  }
`

/**
 * The plant hierarchy stored in conf/settings.yaml (ADR-0005). One query, one mutation, and
 * one retry: the console edits the whole tree locally and saves once, because there
 * is no safe meaning to "rename one site without saying what the rest of the plant
 * now is". Field set matches `07_uns_graphql/test/mutations/test_hierarchy.py`.
 */
export const GET_HIERARCHY_QUERY = `
  query GetHierarchy {
    getHierarchy {
      enterprise
      sites {
        name
        areas {
          name
          kind
          lines {
            name
            cells { name machines }
          }
        }
      }
    }
  }
`

export const SAVE_HIERARCHY_MUTATION = `
  mutation SaveHierarchy($tree: HierarchyTreeInput!, $renames: [PrefixRenameInput!]!) {
    saveHierarchy(tree: $tree, renames: $renames) {
      tree {
        enterprise
        sites {
          name
          areas {
            name
            kind
            lines {
              name
              cells { name machines }
            }
          }
        }
      }
      job {
        oldPrefix
        newPrefix
        status
        rewritten
        error
      }
    }
  }
`

export const RETRY_HIERARCHY_MIGRATE_MUTATION = `
  mutation RetryHierarchyMigrate {
    retryHierarchyMigrate {
      oldPrefix
      newPrefix
      status
      rewritten
      error
    }
  }
`

/**
 * Access Groups: named Asset-tree roots and the Keycloak subjects who belong to them.
 * Field set matches `07_uns_graphql/test/queries/test_access_group.py`.
 */
const ACCESS_GROUP_FIELDS = `
  id
  name
  roots {
    assetId
    path
    segment
    level
  }
  subjects
`

export const GET_ACCESS_GROUPS_QUERY = `
  query GetAccessGroups {
    getAccessGroups {
      ${ACCESS_GROUP_FIELDS}
    }
  }
`

export const SAVE_ACCESS_GROUP_MUTATION = `
  mutation SaveAccessGroup($name: String!, $rootAssetIds: [Int64!]!, $id: Int64) {
    saveAccessGroup(name: $name, rootAssetIds: $rootAssetIds, id: $id) {
      ${ACCESS_GROUP_FIELDS}
    }
  }
`

export const DELETE_ACCESS_GROUP_MUTATION = `
  mutation DeleteAccessGroup($id: Int64!) {
    deleteAccessGroup(id: $id)
  }
`

export const SET_ACCESS_GROUP_MEMBERS_MUTATION = `
  mutation SetAccessGroupMembers($id: Int64!, $subjects: [String!]!) {
    setAccessGroupMembers(id: $id, subjects: $subjects) {
      ${ACCESS_GROUP_FIELDS}
    }
  }
`

/**
 * Flat Asset Model list for the Access Group picker. `id` is the Asset primary key
 * `saveAccessGroup` needs as `rootAssetIds`; path/segment/level drive indent and labels.
 */
export const GET_ASSETS_QUERY = `
  query GetAssets {
    getAssets {
      id
      path
      segment
      level
    }
  }
`

/**
 * Assets & Connectivity (ADR-0008). Servers and tags live in `console.connectivity_*`;
 * the console only edits them through GraphQL, and `opcua_client` polls the catalog.
 */
const CONNECTIVITY_SERVER_FIELDS = `
  id
  name
  protocol
  endpoint
  authMode
  username
  hasPassword
  securityPolicy
  securityMode
  certificate
  hasPrivateKey
  serverCertificate
  lastStatus
  lastError
  lastTestedAt
  createdAt
  updatedAt
  tags {
    serverId
    nodeId
    browsePath
    displayName
    mqttTopic
    subscribed
    createdAt
    updatedAt
  }
`

const CONNECTIVITY_TAG_FIELDS = `
  serverId
  nodeId
  browsePath
  displayName
  mqttTopic
  subscribed
  createdAt
  updatedAt
  assetId
  assetPath
  assetDisplayName
  unitOfMeasure
  semanticClass
  dataType
  labels
`

export const GET_CONNECTIVITY_SERVERS_QUERY = `
  query GetConnectivityServers($protocol: ConnectivityProtocol) {
    getConnectivityServers(protocol: $protocol) {
      ${CONNECTIVITY_SERVER_FIELDS}
    }
  }
`

export const SAVE_CONNECTIVITY_SERVER_MUTATION = `
  mutation SaveConnectivityServer($server: ConnectivityServerInput!) {
    saveConnectivityServer(server: $server) {
      ${CONNECTIVITY_SERVER_FIELDS}
    }
  }
`

export const DELETE_CONNECTIVITY_SERVER_MUTATION = `
  mutation DeleteConnectivityServer($id: String!) {
    deleteConnectivityServer(id: $id)
  }
`

export const TEST_OPCUA_CONNECTION_QUERY = `
  query TestOpcUaConnection($endpoint: String!) {
    testOpcUaConnection(endpoint: $endpoint) {
      ok
      error
      elapsedMs
    }
  }
`

export const BROWSE_OPCUA_QUERY = `
  query BrowseOpcUa($endpoint: String!, $nodeId: String) {
    browseOpcUa(endpoint: $endpoint, nodeId: $nodeId) {
      nodeId
      browseName
      displayName
      browsePath
      nodeClass
      hasChildren
    }
  }
`

export const DISCOVER_OPCUA_VARIABLES_QUERY = `
  query DiscoverOpcUaVariables($endpoint: String!, $nodeId: String) {
    discoverOpcUaVariables(endpoint: $endpoint, nodeId: $nodeId) {
      nodeId
      browseName
      displayName
      browsePath
      nodeClass
      hasChildren
    }
  }
`

export const SUBSCRIBE_OPCUA_VARIABLES_MUTATION = `
  mutation SubscribeOpcUaVariables($serverId: String!, $nodeId: String) {
    subscribeOpcUaVariables(serverId: $serverId, nodeId: $nodeId) {
      ${CONNECTIVITY_TAG_FIELDS}
    }
  }
`

export const UPDATE_CONNECTIVITY_TAG_TOPIC_MUTATION = `
  mutation UpdateConnectivityTagTopic($serverId: String!, $nodeId: String!, $mqttTopic: String!) {
    updateConnectivityTagTopic(serverId: $serverId, nodeId: $nodeId, mqttTopic: $mqttTopic) {
      ${CONNECTIVITY_TAG_FIELDS}
    }
  }
`

export const UNSUBSCRIBE_CONNECTIVITY_TAG_MUTATION = `
  mutation UnsubscribeConnectivityTag($serverId: String!, $nodeId: String!) {
    unsubscribeConnectivityTag(serverId: $serverId, nodeId: $nodeId)
  }
`

export const READ_OPCUA_NODES_QUERY = `
  query ReadOpcUaNodes($endpoint: String!, $nodeIds: [String!]!) {
    readOpcUaNodes(endpoint: $endpoint, nodeIds: $nodeIds) {
      nodeId
      displayName
      browsePath
      value
      dataType
      sourceTimestamp
      serverTimestamp
      status
    }
  }
`

export const SUBSCRIBE_OPCUA_DATA_CHANGES = `
  subscription OpcUaDataChanges($endpoint: String!, $nodeIds: [String!]!) {
    opcUaDataChanges(endpoint: $endpoint, nodeIds: $nodeIds) {
      nodeId
      displayName
      browsePath
      value
      dataType
      sourceTimestamp
      serverTimestamp
      status
    }
  }
`

/**
 * Signal context catalogs and subscribed tags (Task 3 schema). Field set matches
 * `07_uns_graphql/test/mutations/test_connectivity.py`.
 */
export const UNITS_OF_MEASURE_QUERY = `
  query UnitsOfMeasure {
    unitsOfMeasure {
      symbol
      name
    }
  }
`

export const SAVE_UNIT_OF_MEASURE_MUTATION = `
  mutation SaveUnitOfMeasure($symbol: String!, $name: String) {
    saveUnitOfMeasure(symbol: $symbol, name: $name) {
      symbol
      name
    }
  }
`

export const SIGNAL_LABELS_QUERY = `
  query SignalLabels {
    signalLabels
  }
`

export const SAVE_SIGNAL_LABEL_MUTATION = `
  mutation SaveSignalLabel($name: String!) {
    saveSignalLabel(name: $name)
  }
`

export const GET_SUBSCRIBED_SIGNALS_QUERY = `
  query GetSubscribedSignals {
    getSubscribedSignals {
      ${CONNECTIVITY_TAG_FIELDS}
      serverName
    }
  }
`

export const UPDATE_CONNECTIVITY_TAG_MUTATION = `
  mutation UpdateConnectivityTag($serverId: String!, $nodeId: String!, $patch: ConnectivityTagUpdateInput!) {
    updateConnectivityTag(serverId: $serverId, nodeId: $nodeId, patch: $patch) {
      ${CONNECTIVITY_TAG_FIELDS}
    }
  }
`
