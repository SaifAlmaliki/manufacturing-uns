import type { ApolloClient } from '@apollo/client'
import type { Dispatch } from 'react'
import type { UnsAction } from '../../app/uns-reducer'
import { GET_HISTORIC_EVENTS, GET_UNS_NODES, GET_UNS_NODES_BY_PROPERTY } from '../../lib/graphql/operations'
import type { GraphqlHistoricalEvent, GraphqlUnsNode } from '../../lib/graphql/types'
import { parseJsonPayload } from '../../lib/uns/payload'
import { historianTopic } from '../../lib/uns/topics'

export type HistorianRange = { from: Date; to: Date }

export function splitPropertyKeys(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function historianRange(
  preset: '15m' | '1h' | '24h' | 'custom',
  customFrom: string,
  customTo: string,
): HistorianRange | null {
  const to = new Date()
  if (preset === 'custom') {
    if (!customFrom || !customTo) {
      return null
    }
    const from = new Date(customFrom)
    const until = new Date(customTo)
    if (from > until) {
      return null
    }
    return { from, to: until }
  }
  const ms = preset === '15m' ? 15 * 60 * 1000 : preset === '1h' ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000
  return { from: new Date(to.getTime() - ms), to }
}

export function historicPayloadPreview(payload: { data: unknown } | null): string {
  if (!payload) {
    return ''
  }
  const parsed = parseJsonPayload(payload.data)
  if (!parsed.ok) {
    return ''
  }
  const text = JSON.stringify(parsed.value)
  return text.length > 80 ? `${text.slice(0, 77)}…` : text
}

export async function searchUnsNodes(
  client: ApolloClient<unknown>,
  dispatch: Dispatch<UnsAction>,
  topic: string,
  propertyKeys: string[],
): Promise<{ nodes: GraphqlUnsNode[]; error: boolean }> {
  try {
    let nodes: GraphqlUnsNode[] = []
    if (topic && propertyKeys.length === 0) {
      const result = await client.query<{ getUnsNodes: GraphqlUnsNode[] }>({
        query: GET_UNS_NODES,
        variables: { topics: [{ topic }] },
      })
      nodes = result.data.getUnsNodes ?? []
    } else {
      const result = await client.query<{ getUnsNodesByProperty: GraphqlUnsNode[] }>({
        query: GET_UNS_NODES_BY_PROPERTY,
        variables: {
          propertyKeys,
          topics: topic ? [{ topic }] : null,
        },
      })
      nodes = result.data.getUnsNodesByProperty ?? []
    }
    dispatch({ type: 'conn/http', ok: true })
    return { nodes, error: false }
  } catch {
    dispatch({ type: 'conn/http', ok: false })
    return { nodes: [], error: true }
  }
}

export async function loadHistoricEvents(
  client: ApolloClient<unknown>,
  dispatch: Dispatch<UnsAction>,
  namespace: string,
  range: HistorianRange,
): Promise<{ events: GraphqlHistoricalEvent[]; error: boolean }> {
  try {
    const result = await client.query<{ getHistoricEventsInTimeRange: GraphqlHistoricalEvent[] }>({
      query: GET_HISTORIC_EVENTS,
      variables: {
        topics: [{ topic: historianTopic(namespace) }],
        fromDatetime: range.from.toISOString(),
        toDatetime: range.to.toISOString(),
      },
    })
    dispatch({ type: 'conn/http', ok: true })
    return { events: result.data.getHistoricEventsInTimeRange ?? [], error: false }
  } catch {
    dispatch({ type: 'conn/http', ok: false })
    return { events: [], error: true }
  }
}
