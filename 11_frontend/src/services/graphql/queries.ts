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
