import { useApolloClient } from '@apollo/client'
import { useMemo, useRef, useState, type FormEvent } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useUnsDispatch, useUnsState } from '../../app/UnsProvider'
import { Button } from '../../components/ui/button'
import { parseJsonPayload } from '../../lib/uns/payload'
import { graphqlNodesToRecords } from '../tree/graphql-nodes'
import { expandToNamespace } from '../tree/expand-to'
import { getNumericPath, numericLeafPaths } from './numeric-paths'
import {
  historianRange,
  historicPayloadPreview,
  loadHistoricEvents,
  searchUnsNodes,
  splitPropertyKeys,
} from './useExploreQueries'

type Match = { namespace: string; nodeType: string; lastUpdated: string }

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
  const [events, setEvents] = useState<Awaited<ReturnType<typeof loadHistoricEvents>>['events']>([])
  const [eventsMessage, setEventsMessage] = useState<string | null>(null)
  const [trendPath, setTrendPath] = useState('')

  const range = historianRange(preset, customFrom, customTo)
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
    const keys = splitPropertyKeys(properties)
    const t = topic.trim()
    if (!t && keys.length === 0) {
      setHint('Enter a topic or property.')
      setMatches(null)
      return
    }
    setHint('')
    const result = await searchUnsNodes(client, dispatch, t, keys)
    if (result.error) {
      setHint("Can't reach GraphQL")
      return
    }
    const records = graphqlNodesToRecords(result.nodes)
    setMatches(records.map((n) => ({ namespace: n.namespace, nodeType: n.nodeType, lastUpdated: n.lastUpdated })))
    if (records.length === 0) {
      setHint('No nodes match.')
    }
  }

  async function loadHistory() {
    if (!state.selectedNamespace || !range) {
      return
    }
    const result = await loadHistoricEvents(client, dispatch, state.selectedNamespace, range)
    setEvents(result.events)
    setEventsMessage(result.events.length === 0 || result.error ? 'No events in this range.' : null)
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
            <input
              type="datetime-local"
              aria-label="From"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
            />
            <input
              type="datetime-local"
              aria-label="To"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
            />
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
                <th>Payload</th>
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
                  <td>{historicPayloadPreview(event.payload)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {numericFields.length > 0 && events.length > 0 ? (
          <div className="h-40">
            <select aria-label="Numeric field" value={trendPath} onChange={(e) => setTrendPath(e.target.value)}>
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
