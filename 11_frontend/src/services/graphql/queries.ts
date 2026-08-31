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
          data
        }
        ... on BytesPayload {
          data
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
