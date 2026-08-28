import { useApolloClient } from '@apollo/client'
import { useMemo, useRef, useState, type FormEvent } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useUnsDispatch, useUnsState } from '../../app/UnsProvider'
import { Button } from '../../components/ui/button'
import { GET_HISTORIC_EVENTS, GET_UNS_NODES, GET_UNS_NODES_BY_PROPERTY } from '../../lib/graphql/operations'
import type { GraphqlHistoricalEvent, GraphqlUnsNode } from '../../lib/graphql/types'
import { parseJsonPayload } from '../../lib/uns/payload'
import { historianTopic } from '../../lib/uns/topics'
import { graphqlNodesToRecords } from '../tree/graphql-nodes'
import { expandToNamespace } from '../tree/expand-to'
import { getNumericPath, numericLeafPaths } from './numeric-paths'

type Match = { namespace: string; nodeType: string; lastUpdated: string }

function splitKeys(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function presetRange(preset: '15m' | '1h' | '24h' | 'custom', customFrom: string, customTo: string): {
  from: Date
  to: Date
} | null {
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

export function ExplorePanel() {
  const state = useUnsState()
  const dispatch = useUnsDispatch()
  const client = useApolloClient()
  const stateRef = useRef(state)
  stateRef.current = state

  const [topic, setTopic] = useState('')
  const [properties, setProperties] = useState('')
  const [hint, setHint] = useState('Enter a topic or property.')
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [preset, setPreset] = useState<'15m' | '1h' | '24h' | 'custom'>('1h')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [events, setEvents] = useState<GraphqlHistoricalEvent[]>([])
  const [eventsMessage, setEventsMessage] = useState<string | null>(null)
  const [trendPath, setTrendPath] = useState('')

  const range = presetRange(preset, customFrom, customTo)
  const invalidRange = preset === 'custom' && customFrom && customTo && new Date(customFrom) > new Date(customTo)

  const numericFields = useMemo(() => {
    const set = new Set<string>()
    for (const event of events) {
      const parsed = event.payload ? parseJsonPayload(event.payload.data) : { ok: false as const }
      if (parsed.ok) {
        for (const path of numericLeafPaths(parsed.value)) {
          set.add(path)
        }
      }
    }
    return [...set]
  }, [events])

  const trendData = useMemo(() => {
    if (!trendPath) {
      return []
    }
    const points: { t: string; v: number }[] = []
    for (const event of events) {
      const parsed = event.payload ? parseJsonPayload(event.payload.data) : { ok: false as const }
      if (!parsed.ok) {
        continue
      }
      const v = getNumericPath(parsed.value, trendPath)
      if (v !== undefined) {
        points.push({ t: event.timestamp, v })
      }
    }
    return points
  }, [events, trendPath])

  async function onSearch(event: FormEvent) {
    event.preventDefault()
    const keys = splitKeys(properties)
    const t = topic.trim()
    if (!t && keys.length === 0) {
      setHint('Enter a topic or property.')
      setMatches(null)
      return
    }
    setHint('')
    try {
      let nodes: GraphqlUnsNode[] = []
      if (t && keys.length === 0) {
        const result = await client.query<{ getUnsNodes: GraphqlUnsNode[] }>({
          query: GET_UNS_NODES,
          variables: { topics: [{ topic: t }] },
        })
        nodes = result.data.getUnsNodes ?? []
      } else {
        const result = await client.query<{ getUnsNodesByProperty: GraphqlUnsNode[] }>({
          query: GET_UNS_NODES_BY_PROPERTY,
          variables: {
            propertyKeys: keys,
            topics: t ? [{ topic: t }] : null,
          },
        })
        nodes = result.data.getUnsNodesByProperty ?? []
      }
      dispatch({ type: 'conn/http', ok: true })
      const records = graphqlNodesToRecords(nodes)
      setMatches(records.map((n) => ({ namespace: n.namespace, nodeType: n.nodeType, lastUpdated: n.lastUpdated })))
      if (records.length === 0) {
        setHint('No nodes match.')
      }
    } catch {
      dispatch({ type: 'conn/http', ok: false })
      setHint("Can't reach GraphQL")
    }
  }

  async function loadHistory() {
    if (!state.selectedNamespace || !range) {
      return
    }
    try {
      const result = await client.query<{ getHistoricEventsInTimeRange: GraphqlHistoricalEvent[] }>({
        query: GET_HISTORIC_EVENTS,
        variables: {
          topics: [{ topic: historianTopic(state.selectedNamespace) }],
          fromDatetime: range.from.toISOString(),
          toDatetime: range.to.toISOString(),
        },
      })
      const rows = result.data.getHistoricEventsInTimeRange ?? []
      setEvents(rows)
      setEventsMessage(rows.length === 0 ? 'No events in this range' : null)
      dispatch({ type: 'conn/http', ok: true })
    } catch {
      setEvents([])
      setEventsMessage('No events in this range')
      dispatch({ type: 'conn/http', ok: false })
    }
  }

  return (
    <section aria-label="explore" className="flex h-full flex-col overflow-auto p-3 text-sm">
      <form className="space-y-2" onSubmit={onSearch}>
        <input
          className="w-full rounded border border-console-border bg-console-panel px-2 py-1"
          placeholder="MQTT topic"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />
        <input
          className="w-full rounded border border-console-border bg-console-panel px-2 py-1"
          placeholder="Property keys"
          value={properties}
          onChange={(e) => setProperties(e.target.value)}
        />
        <Button type="submit">Search</Button>
      </form>
      {hint ? <p className="mt-2 text-console-muted">{hint}</p> : null}
      {matches ? (
        <ul className="mt-2 max-h-40 overflow-auto border border-console-border">
          {matches.map((m) => (
            <li key={m.namespace}>
              <button
                type="button"
                className="block w-full px-2 py-1 text-left hover:bg-console-panel"
                onClick={() => {
                  void expandToNamespace(() => stateRef.current, dispatch, client, m.namespace)
                }}
              >
                {m.namespace} · {m.nodeType}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-4 space-y-2 border-t border-console-border pt-3">
        <h3 className="text-xs uppercase text-console-muted">Historian</h3>
        <div className="flex flex-wrap gap-2">
          {(['15m', '1h', '24h', 'custom'] as const).map((p) => (
            <Button key={p} type="button" onClick={() => setPreset(p)}>
              {p}
            </Button>
          ))}
        </div>
        {preset === 'custom' ? (
          <div className="flex gap-2">
            <input type="datetime-local" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
            <input type="datetime-local" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
          </div>
        ) : null}
        {invalidRange ? <p className="text-console-danger">From must be before to.</p> : null}
        <Button type="button" disabled={!state.selectedNamespace || !!invalidRange} onClick={() => void loadHistory()}>
          Load history
        </Button>
        {eventsMessage ? <p className="text-console-muted">{eventsMessage}</p> : null}
        {events.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-console-muted">
                <th>Time</th>
                <th>Topic</th>
                <th>Publisher</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event, i) => (
                <tr
                  key={`${event.timestamp}-${i}`}
                  className="cursor-pointer hover:bg-console-panel"
                  onClick={() => {
                    const parsed = event.payload ? parseJsonPayload(event.payload.data) : { ok: false as const }
                    dispatch({
                      type: 'ui/select-historic-event',
                      event: {
                        topic: event.topic,
                        timestamp: event.timestamp,
                        publisher: event.publisher,
                        payload: parsed.ok ? parsed.value : null,
                      },
                    })
                  }}
                >
                  <td>{event.timestamp}</td>
                  <td>{event.topic}</td>
                  <td>{event.publisher}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {numericFields.length > 0 && events.length > 0 ? (
          <div className="h-40">
            <select value={trendPath} onChange={(e) => setTrendPath(e.target.value)}>
              <option value="">Numeric field</option>
              {numericFields.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {trendPath ? (
              <ResponsiveContainer width="100%" height="80%">
                <LineChart data={trendData}>
                  <XAxis dataKey="t" hide />
                  <YAxis width={40} />
                  <Tooltip />
                  <Line type="monotone" dataKey="v" stroke="#3dd6c3" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  )
}
