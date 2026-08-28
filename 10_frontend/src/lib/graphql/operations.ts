import { gql } from '@apollo/client'

export const GET_UNS_NODES = gql`
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

export const GET_UNS_NODES_BY_PROPERTY = gql`
  query GetUnsNodesByProperty($propertyKeys: [String!]!, $topics: [MQTTTopicInput!]) {
    getUnsNodesByProperty(propertyKeys: $propertyKeys, topics: $topics) {
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

export const GET_HISTORIC_EVENTS = gql`
  query GetHistoricEvents(
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

export const MQTT_FEED = gql`
  subscription MqttFeed($topics: [MQTTTopicInput!]!) {
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
