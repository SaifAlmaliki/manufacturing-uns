/**
 * Why the simulator is not doing what was expected (spec 7.2).
 *
 * Named ...Panel rather than ...Diagnostics so it does not read as the SimulatorDiagnostics
 * response type it consumes.
 *
 * Five things, in the order they get checked when something is wrong: the broker, what the
 * profile actually expanded to against what it asked for, the templates that matched nothing,
 * the devices that are failing to publish, and the live Platform Observability feed.
 */

import React, { useEffect } from 'react'
import { AlertTriangle, Radio, Server, Stethoscope } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'
import { useTheme } from '../../context/ThemeContext'
import { GRAFANA_DASHBOARDS, GrafanaEmbed } from '../common/GrafanaEmbed'

export const SimulatorDiagnosticsPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, diagnostics, telemetry, refreshDiagnostics } = simulator
  const { isDark } = useTheme()

  useEffect(() => {
    void refreshDiagnostics()
    const timer = window.setInterval(() => void refreshDiagnostics(), 5000)
    return () => window.clearInterval(timer)
  }, [refreshDiagnostics])

  const report = diagnostics?.report
  const failing = diagnostics?.failing_devices ?? []

  return (
    <div className="p-3 md:p-4 space-y-3">
      <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
        <Stethoscope className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
        <span>Simulator Diagnostics</span>
      </h3>

      {(report?.warnings ?? []).map((warning) => (
        <div
          key={warning}
          className="p-2.5 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 text-[11px] font-mono text-amber-800 dark:text-[#FFC107] flex items-start gap-2"
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{warning}</span>
        </div>
      ))}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1.5">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider flex items-center gap-1.5">
            <Server className="w-3.5 h-3.5" />
            <span>MQTT broker</span>
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Connected</span>
              <span
                className={
                  status?.broker_connected
                    ? 'text-emerald-600 dark:text-emerald-400 font-bold'
                    : 'text-rose-600 dark:text-rose-400 font-bold'
                }
              >
                {status ? (status.broker_connected ? 'YES' : 'NO') : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Failed publishes</span>
              <span
                className={`tabular-nums ${
                  (status?.failed_total ?? 0) > 0
                    ? 'text-rose-600 dark:text-rose-400 font-bold'
                    : 'text-[#0F172A] dark:text-[#F8FAFC]'
                }`}
              >
                {(status?.failed_total ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Devices failing</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {failing.length} / {status?.device_count ?? 0}
              </span>
            </div>
          </div>
        </div>

        <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1.5">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
            What the profile expanded to
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Devices</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.devices ?? '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Signals</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.signals ?? '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Serves links</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.serves_links ?? '—'}
              </span>
            </div>
            {Object.entries(report?.per_tier ?? {}).map(([tier, count]) => (
              <div key={tier} className="flex justify-between">
                <span className="text-[#64748B] dark:text-[#94A3B8]">
                  {TIER_LABELS[tier] ?? tier}
                </span>
                <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">{count}</span>
              </div>
            ))}
            {Object.entries(report?.per_family ?? {}).map(([family, count]) => (
              <div key={family} className="flex justify-between">
                <span className="text-[#64748B] dark:text-[#94A3B8]">family: {family}</span>
                <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {(report?.unmatched_templates ?? []).length > 0 && (
        <div className="p-2.5 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider mb-1.5">
            Templates that matched nothing ({report?.unmatched_templates.length})
          </div>
          <div className="font-mono text-[10px] text-amber-700 dark:text-[#FFC107] space-y-0.5">
            {(report?.unmatched_templates ?? []).map((template) => (
              <div key={template} className="break-all">
                {template}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B]">
          Devices needing attention ({failing.length})
        </div>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Device</th>
                <th className="text-left px-3 py-1.5">Client id</th>
                <th className="text-left px-3 py-1.5">Connected</th>
                <th className="text-right px-3 py-1.5">OK</th>
                <th className="text-right px-3 py-1.5">Failed</th>
                <th className="text-right px-3 py-1.5">Reconnects</th>
                <th className="text-left px-3 py-1.5">Last error</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {failing.map((device) => (
                <tr key={device.device_id} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5">{device.device_id}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.client_id}</td>
                  <td className="px-3 py-1.5">{device.connected ? 'yes' : 'no'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {device.publish_ok.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-rose-600 dark:text-rose-400">
                    {device.publish_fail.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {device.reconnects}
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8] truncate max-w-xs">
                    {device.last_error ?? '—'}
                  </td>
                </tr>
              ))}
              {failing.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-3 text-center text-emerald-600 dark:text-emerald-400">
                    Every device is connected and publishing.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Radio className="w-3.5 h-3.5" />
          <span>Platform Observability feed — uns/platform/simulator/#</span>
        </div>
        <div className="max-h-64 overflow-y-auto divide-y divide-[#E2E8F0]/60 dark:divide-[#1E293B]/60">
          {telemetry.map((event, index) => (
            <div key={`${event.receivedAt}-${index}`} className="px-3 py-1.5 font-mono text-[10px]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-amber-700 dark:text-[#FFC107] truncate">{event.topic}</span>
                <span className="text-[#64748B] shrink-0 tabular-nums">
                  {event.receivedAt.slice(11, 19)}
                </span>
              </div>
              <div className="text-[#64748B] dark:text-[#94A3B8] break-all">
                {typeof event.payload === 'object' && event.payload !== null
                  ? JSON.stringify(event.payload)
                  : String(event.payload)}
              </div>
            </div>
          ))}
          {telemetry.length === 0 && (
            <div className="px-3 py-3 text-center font-mono text-[10px] text-[#64748B]">
              Nothing received yet. The status heartbeat publishes every ten seconds.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] p-3">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider mb-1.5">
          Sample topics
        </div>
        <div className="font-mono text-[10px] text-[#64748B] dark:text-[#94A3B8] space-y-0.5">
          {(diagnostics?.sample_topics ?? []).map((topic) => (
            <div key={topic} className="break-all">
              {topic}
            </div>
          ))}
          {(diagnostics?.sample_topics ?? []).length === 0 && <div>—</div>}
        </div>
      </div>

      <div
        id="simulator-grafana-platform"
        className="h-[520px] rounded-lg overflow-hidden border border-[#E2E8F0] dark:border-[#1E293B] bg-[#111114]"
      >
        <GrafanaEmbed
          uid={GRAFANA_DASHBOARDS.platform.uid}
          theme={isDark ? 'dark' : 'light'}
          title="Platform Observability"
        />
      </div>
    </div>
  )
}
