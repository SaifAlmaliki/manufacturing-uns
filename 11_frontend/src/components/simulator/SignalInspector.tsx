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

/** Points kept per topic. Twenty is a shape; a hundred would be a chart nobody asked for. */
const SPARK_POINTS = 20

/**
 * The three values `Signal.status()` returns in plan A, from its own limit check. This is
 * not MQTT quality — every value here was generated successfully, so a `quality` column
 * would read `Good` on every row forever and teach an operator to ignore the column that
 * does mean something.
 */
const SIGNAL_STATUS_STYLES: Record<string, string> = {
  Normal: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  Warning: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107]',
  Alarm: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400',
}

const Sparkline: React.FC<{ points: number[] }> = ({ points }) => {
  if (points.length < 2) {
    return <span className="text-[#64748B] text-[9px]">waiting…</span>
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
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1" className="text-[#FFC107]" />
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
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[220px]">
          <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-signal-device">
            DEVICE:
          </label>
          <select
            id="simulator-signal-device"
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            className="w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-sm text-[#FF7A00] focus:border-[#FF7A00]/50 focus:outline-none"
          >
            <option value="">— select a device —</option>
            {devices.map((device) => (
              <option key={device.id} value={device.id}>
                {device.id} — {device.equipment} ({device.signal_count})
              </option>
            ))}
          </select>
        </div>
        <button
          id="simulator-refresh-signals"
          disabled={selectedId === '' || loading}
          onClick={() => void signals(selectedId).then(setRows)}
          className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-[#F1F5F9] dark:bg-[#1E293B] border-[#E2E8F0] dark:border-[#334155] text-[#0F172A] dark:text-[#F8FAFC] hover:brightness-110 cursor-pointer disabled:text-[#94A3B8] disabled:cursor-not-allowed"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh values</span>
        </button>
        {selected && (
          <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px] truncate max-w-full">
            {selected.topic_prefix}
          </span>
        )}
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Gauge className="w-3.5 h-3.5" />
          <span>Signals ({rows.length})</span>
        </div>
        <div className="max-h-[28rem] overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Signal</th>
                <th className="text-left px-3 py-1.5">Unit of Measure</th>
                <th className="text-left px-3 py-1.5">Tier</th>
                <th className="text-right px-3 py-1.5">Value</th>
                <th className="text-left px-3 py-1.5">Status</th>
                <th className="text-left px-3 py-1.5">Live</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {rows.map((signal) => (
                <tr key={signal.topic} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5" title={signal.topic}>
                    {signal.name}
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{signal.unit || '—'}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
                    {TIER_LABELS[signal.tier] ?? signal.tier}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{formatValue(signal.value)}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${SIGNAL_STATUS_STYLES[signal.status] ?? SIGNAL_STATUS_STYLES.Normal}`}
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
                  <td colSpan={6} className="px-3 py-4 text-center text-[#64748B]">
                    {selectedId === '' ? 'Select a device.' : 'This device publishes no signals.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
