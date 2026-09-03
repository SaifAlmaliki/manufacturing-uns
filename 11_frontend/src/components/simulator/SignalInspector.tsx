/**
 * Every signal on one device: name, Unit of Measure, tier, current value, limit status and
 * topic (spec 7.2), plus a live sparkline per topic.
 *
 * The table is a snapshot from GET /devices/{id}/signals; the sparkline comes from the
 * device's own MQTT topics through the existing GraphQL subscription. Both, because they
 * answer different questions: the table proves the signal exists and is configured, the
 * sparkline proves it is moving. A signal frozen at a plausible value is the failure this
 * page is here to catch, and only the second one shows it.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { Gauge, RefreshCw } from 'lucide-react'
import { unsGraphQLClient } from '../../services/graphql/client'
import type { SimulatorSignal } from '../../types/simulator'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'
import { BtnSecondary, ConsoleCard, FilterToolbar } from '../ui/console-ui'

/** Points kept per topic. Twenty is a shape; a hundred would be a chart nobody asked for. */
const SPARK_POINTS = 20

/**
 * The three values `Signal.status()` returns in plan A, from its own limit check. This is
 * not MQTT quality — every value here was generated successfully, so a `quality` column
 * would read `Good` on every row forever and teach an operator to ignore the column that
 * does mean something.
 */
const SIGNAL_STATUS_STYLES: Record<string, string> = {
  Normal: 'bg-emerald-500/10 text-emerald-400',
  Warning: 'bg-[#FF7A00]/10 text-[#FF7A00]',
  Alarm: 'bg-rose-500/10 text-rose-400',
}

const Sparkline: React.FC<{ points: number[] }> = ({ points }) => {
  if (points.length < 2) {
    return <span className="text-[9px] text-zinc-500">waiting…</span>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 60
      const y = 14 - ((value - min) / span) * 12
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width="60" height="16" viewBox="0 0 60 16" className="overflow-visible">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1" className="text-[#FF7A00]" />
    </svg>
  )
}

function formatValue(value: SimulatorSignal['value']): string {
  if (value === null) {
    return '—'
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(3)
  }
  return String(value)
}

export const SignalInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { devices, signals } = simulator
  const [selectedId, setSelectedId] = useState('')
  const [rows, setRows] = useState<SimulatorSignal[]>([])
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<Record<string, number[]>>({})

  const selected = useMemo(
    () => devices.find((device) => device.id === selectedId),
    [devices, selectedId],
  )

  useEffect(() => {
    if (selectedId === '' && devices.length > 0) {
      setSelectedId(devices[0].id)
    }
  }, [devices, selectedId])

  useEffect(() => {
    if (selectedId === '') {
      return
    }
    let cancelled = false
    setLoading(true)
    setHistory({})
    void signals(selectedId).then((result) => {
      if (!cancelled) {
        setRows(result)
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [selectedId, signals])

  useEffect(() => {
    if (!selected) {
      return
    }
    return unsGraphQLClient.subscribeMqttMessages([`${selected.topic_prefix}/#`], (message) => {
      const payload = message.payload
      if (payload === null || typeof payload !== 'object') {
        return
      }
      const numbers = Object.values(payload).filter(
        (candidate): candidate is number => typeof candidate === 'number',
      )
      if (numbers.length === 0) {
        return
      }
      setHistory((previous) => ({
        ...previous,
        [message.topic]: [...(previous[message.topic] ?? []), numbers[0]].slice(-SPARK_POINTS),
      }))
    })
  }, [selected])

  return (
    <div className="flex flex-col gap-3">
      <FilterToolbar
        selects={[
          {
            value: selectedId,
            onChange: setSelectedId,
            'aria-label': 'Device',
            options: [
              { value: '', label: '— select a device —' },
              ...devices.map((device) => ({
                value: device.id,
                label: `${device.id} — ${device.equipment} (${device.signal_count})`,
              })),
            ],
          },
        ]}
        trailing={
          <>
            {selected && (
              <span className="max-w-full truncate px-2 py-0.5 font-mono text-[10px] text-zinc-500">
                {selected.topic_prefix}
              </span>
            )}
            <BtnSecondary
              id="simulator-refresh-signals"
              disabled={selectedId === '' || loading}
              onClick={() => void signals(selectedId).then(setRows)}
              className="px-2.5 py-1.5 text-xs"
            >
              <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </BtnSecondary>
          </>
        }
      />

      <ConsoleCard padding="none" className="overflow-hidden">
        <div className="flex items-center gap-1.5 border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-500">
          <Gauge className="size-3.5" />
          <span>Signals ({rows.length})</span>
        </div>
        <div className="max-h-[28rem] overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[9px] uppercase text-zinc-500">
              <tr className="border-b border-zinc-800">
                <th className="px-3 py-1.5 text-left">Signal</th>
                <th className="px-3 py-1.5 text-left">Unit of Measure</th>
                <th className="px-3 py-1.5 text-left">Tier</th>
                <th className="px-3 py-1.5 text-right">Value</th>
                <th className="px-3 py-1.5 text-left">Status</th>
                <th className="px-3 py-1.5 text-left">Live</th>
              </tr>
            </thead>
            <tbody className="text-white">
              {rows.map((signal) => (
                <tr key={signal.topic} className="border-b border-zinc-800/60">
                  <td className="px-3 py-1.5" title={signal.topic}>
                    {signal.name}
                  </td>
                  <td className="px-3 py-1.5 text-zinc-400">{signal.unit || '—'}</td>
                  <td className="px-3 py-1.5 text-zinc-400">
                    {TIER_LABELS[signal.tier] ?? signal.tier}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{formatValue(signal.value)}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${SIGNAL_STATUS_STYLES[signal.status] ?? SIGNAL_STATUS_STYLES.Normal}`}
                    >
                      {signal.status}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    <Sparkline points={history[signal.topic] ?? []} />
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-zinc-500">
                    {selectedId === '' ? 'Select a device.' : 'This device publishes no signals.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </ConsoleCard>
    </div>
  )
}
