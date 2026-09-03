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
import { AlertTriangle, Radio, Server } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'
import { useTheme } from '../../context/ThemeContext'
import { GRAFANA_DASHBOARDS, GrafanaEmbed } from '../common/GrafanaEmbed'
import { ConsoleCard } from '../ui/console-ui'

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
    <div className="flex flex-col gap-3">
      {(report?.warnings ?? []).map((warning) => (
        <div
          key={warning}
          className="flex items-start gap-2 rounded-lg border border-[#FF7A00]/30 bg-[#FF7A00]/10 p-2.5 font-mono text-[11px] text-[#FF7A00]"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{warning}</span>
        </div>
      ))}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ConsoleCard padding="sm" className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
            <Server className="size-3.5" />
            <span>MQTT broker</span>
          </div>
          <div className="space-y-1 font-mono text-[11px]">
            <div className="flex justify-between">
              <span className="text-zinc-500">Connected</span>
              <span className={status?.broker_connected ? 'font-bold text-emerald-400' : 'font-bold text-rose-400'}>
                {status ? (status.broker_connected ? 'YES' : 'NO') : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Failed publishes</span>
              <span
                className={`tabular-nums ${(status?.failed_total ?? 0) > 0 ? 'font-bold text-rose-400' : 'text-white'}`}
              >
                {(status?.failed_total ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Devices failing</span>
              <span className="tabular-nums text-white">
                {failing.length} / {status?.device_count ?? 0}
              </span>
            </div>
          </div>
        </ConsoleCard>

        <ConsoleCard padding="sm" className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">What the profile expanded to</div>
          <div className="space-y-1 font-mono text-[11px]">
            <div className="flex justify-between">
              <span className="text-zinc-500">Devices</span>
              <span className="tabular-nums text-white">{report?.devices ?? '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Signals</span>
              <span className="tabular-nums text-white">{report?.signals ?? '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Serves links</span>
              <span className="tabular-nums text-white">{report?.serves_links ?? '—'}</span>
            </div>
            {Object.entries(report?.per_tier ?? {}).map(([tier, count]) => (
              <div key={tier} className="flex justify-between">
                <span className="text-zinc-500">{TIER_LABELS[tier] ?? tier}</span>
                <span className="tabular-nums text-white">{count}</span>
              </div>
            ))}
            {Object.entries(report?.per_family ?? {}).map(([family, count]) => (
              <div key={family} className="flex justify-between">
                <span className="text-zinc-500">family: {family}</span>
                <span className="tabular-nums text-white">{count}</span>
              </div>
            ))}
          </div>
        </ConsoleCard>
      </div>

      {(report?.unmatched_templates ?? []).length > 0 && (
        <ConsoleCard padding="sm">
          <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
            Templates that matched nothing ({report?.unmatched_templates.length})
          </div>
          <div className="space-y-0.5 font-mono text-[10px] text-[#FF7A00]">
            {(report?.unmatched_templates ?? []).map((template) => (
              <div key={template} className="break-all">
                {template}
              </div>
            ))}
          </div>
        </ConsoleCard>
      )}

      <ConsoleCard padding="none" className="overflow-hidden">
        <div className="border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-500">
          Devices needing attention ({failing.length})
        </div>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[9px] uppercase text-zinc-500">
              <tr className="border-b border-zinc-800">
                <th className="px-3 py-1.5 text-left">Device</th>
                <th className="px-3 py-1.5 text-left">Client id</th>
                <th className="px-3 py-1.5 text-left">Connected</th>
                <th className="px-3 py-1.5 text-right">OK</th>
                <th className="px-3 py-1.5 text-right">Failed</th>
                <th className="px-3 py-1.5 text-right">Reconnects</th>
                <th className="px-3 py-1.5 text-left">Last error</th>
              </tr>
            </thead>
            <tbody className="text-white">
              {failing.map((device) => (
                <tr key={device.device_id} className="border-b border-zinc-800/60">
                  <td className="px-3 py-1.5">{device.device_id}</td>
                  <td className="px-3 py-1.5 text-zinc-400">{device.client_id}</td>
                  <td className="px-3 py-1.5">{device.connected ? 'yes' : 'no'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">
                    {device.publish_ok.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-rose-400">
                    {device.publish_fail.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">{device.reconnects}</td>
                  <td className="max-w-xs truncate px-3 py-1.5 text-zinc-400">{device.last_error ?? '—'}</td>
                </tr>
              ))}
              {failing.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-3 text-center text-emerald-400">
                    Every device is connected and publishing.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </ConsoleCard>

      <ConsoleCard padding="none" className="overflow-hidden">
        <div className="flex items-center gap-1.5 border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-500">
          <Radio className="size-3.5" />
          <span>Platform Observability feed — uns/platform/simulator/#</span>
        </div>
        <div className="max-h-64 divide-y divide-zinc-800 overflow-y-auto">
          {telemetry.map((event, index) => (
            <div key={`${event.receivedAt}-${index}`} className="px-3 py-1.5 font-mono text-[10px]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-[#FF7A00]">{event.topic}</span>
                <span className="shrink-0 tabular-nums text-zinc-500">{event.receivedAt.slice(11, 19)}</span>
              </div>
              <div className="break-all text-zinc-400">
                {typeof event.payload === 'object' && event.payload !== null
                  ? JSON.stringify(event.payload)
                  : String(event.payload)}
              </div>
            </div>
          ))}
          {telemetry.length === 0 && (
            <div className="px-3 py-3 text-center font-mono text-[10px] text-zinc-500">
              Nothing received yet. The status heartbeat publishes every ten seconds.
            </div>
          )}
        </div>
      </ConsoleCard>

      <ConsoleCard padding="sm">
        <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-500">Sample topics</div>
        <div className="space-y-0.5 font-mono text-[10px] text-zinc-400">
          {(diagnostics?.sample_topics ?? []).map((topic) => (
            <div key={topic} className="break-all">
              {topic}
            </div>
          ))}
          {(diagnostics?.sample_topics ?? []).length === 0 && <div>—</div>}
        </div>
      </ConsoleCard>

      <ConsoleCard id="simulator-grafana-platform" padding="none" className="h-[420px] overflow-hidden">
        <GrafanaEmbed
          uid={GRAFANA_DASHBOARDS.platform.uid}
          theme={isDark ? 'dark' : 'light'}
          title="Platform Observability"
        />
      </ConsoleCard>
    </div>
  )
}
