/**
 * What the simulator is doing right now, and the four buttons that change it (spec 7.1).
 *
 * Every number here comes from the polled /status body. Nothing is derived, accumulated or
 * remembered locally: a console that counted messages itself would drift from the
 * simulator within minutes and there would be no way to tell which of the two was right.
 */

import React from 'react'
import { Activity, AlertTriangle, Pause, Play, RotateCcw, Square, Lock, WifiOff } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { useSimulator } from '../../hooks/useSimulator'
import type { RunAction, RunState } from '../../types/simulator'

export type SimulatorState = ReturnType<typeof useSimulator>

/**
 * The seven cadence tiers, in the order an engineer thinks about them: fastest first.
 *
 * The keys are plan A's tier names exactly. A label map keyed on anything else silently
 * renders the raw tier name, which is the one failure `Record<string, string>` cannot
 * catch for us.
 */
export const TIER_LABELS: Record<string, string> = {
  fast: 'Fast (sub-second)',
  process: 'Process',
  energy: 'Energy & Utilities',
  status: 'Status & Condition',
  meter: 'Meters & Totalisers',
  lab: 'Lab & Quality',
  event: 'Event-driven',
}

const RUN_STATE_STYLES: Record<RunState, string> = {
  running: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
  paused: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  starting: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  stopped: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
}

function formatUptime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m ${total % 60}s`
}

const Tile: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
    <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">{label}</div>
    <div className={`text-base font-mono font-bold tabular-nums ${tone ?? 'text-[#0F172A] dark:text-[#F8FAFC]'}`}>
      {value}
    </div>
  </div>
)

export const SimulatorStatusPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { hasPermission } = useAuth()
  const canControl = hasPermission('simulator_control')
  const { status, offline, lastError, busy, run } = simulator

  // The four transitions the API accepts, and when each one is meaningful. Offering
  // `resume` on a stopped simulator would produce a 422 the operator cannot act on, so the
  // button that cannot work is the button that is not enabled.
  const runState: RunState = status?.run_state ?? 'stopped'
  const actions: Array<{ action: RunAction; label: string; icon: typeof Play; enabledIn: RunState[] }> = [
    { action: 'start', label: 'Start', icon: Play, enabledIn: ['stopped'] },
    { action: 'pause', label: 'Pause', icon: Pause, enabledIn: ['running'] },
    { action: 'resume', label: 'Resume', icon: RotateCcw, enabledIn: ['paused'] },
    { action: 'stop', label: 'Stop', icon: Square, enabledIn: ['running', 'paused', 'starting'] },
  ]

  const totalRate = status
    ? Object.values(status.msg_per_sec).reduce((sum, rate) => sum + rate, 0)
    : 0

  return (
    <div className="p-3 md:p-4 space-y-3">
      {offline && (
        <div className="p-3 rounded-lg bg-[#111114] border border-[#334155] flex items-start gap-2">
          <WifiOff className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div className="text-[11px] text-[#94A3B8] font-mono">
            <div className="text-[#F8FAFC] font-bold">No simulator is answering on /simulator</div>
            {/* Stated plainly, because on most installs this is correct rather than broken. */}
            <div className="mt-0.5">
              The simulator is optional. If one should be running, check that 99_simulator is up and
              that port 8099 is reachable. Values below are the last that were read.
            </div>
          </div>
        </div>
      )}

      {status?.overrides_active && (
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-[#FFC107] shrink-0 mt-0.5" />
          <div className="text-[11px] font-mono text-amber-800 dark:text-[#FFC107]">
            <span className="font-bold">Runtime overrides are active.</span> The running plant no longer
            matches the profile files on disk, and nothing here is written back to them. A restart
            returns the simulator to <code>conf/simulator/</code>.
          </div>
        </div>
      )}

      {lastError && lastError.kind === 'http' && (
        <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 text-[11px] font-mono text-rose-700 dark:text-rose-400">
          {lastError.field ? `${lastError.field}: ${lastError.message}` : lastError.message}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`px-2.5 py-1 rounded border text-[10px] font-mono font-bold uppercase tracking-wider ${RUN_STATE_STYLES[runState]}`}
        >
          {runState}
        </span>
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px]">
          profile: {status?.profile ?? '—'}
        </span>
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px]">
          seed: {status?.seed ?? '—'}
        </span>

        <div className="flex-1" />

        {!canControl && (
          <span className="px-2 py-0.5 rounded bg-[#1E293B] border border-[#334155] text-[#94A3B8] text-[9px] flex items-center gap-1">
            <Lock className="w-3 h-3 text-rose-400" />
            <span>Read-Only Mode</span>
          </span>
        )}

        <div className="flex items-center gap-1.5">
          {actions.map(({ action, label, icon: Icon, enabledIn }) => {
            const disabled = !canControl || busy || offline || !enabledIn.includes(runState)
            return (
              <button
                key={action}
                id={`simulator-run-${action}`}
                disabled={disabled}
                onClick={() => void run(action)}
                title={canControl ? label : 'Requires the Simulator Control permission'}
                className={`px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 transition-colors ${
                  disabled
                    ? 'bg-[#F1F5F9] dark:bg-[#1E293B] border-[#E2E8F0] dark:border-[#334155] text-[#94A3B8] cursor-not-allowed'
                    : 'bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer'
                }`}
              >
                <Icon className="w-3 h-3" />
                <span>{label}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        <Tile label="Devices" value={String(status?.device_count ?? 0)} />
        <Tile label="Signals" value={String(status?.signal_count ?? 0)} />
        <Tile label="Msg / sec" value={totalRate.toFixed(1)} />
        <Tile label="Published" value={(status?.published_total ?? 0).toLocaleString()} />
        <Tile
          label="Failed"
          value={(status?.failed_total ?? 0).toLocaleString()}
          tone={
            (status?.failed_total ?? 0) > 0
              ? 'text-rose-600 dark:text-rose-400'
              : 'text-[#0F172A] dark:text-[#F8FAFC]'
          }
        />
        <Tile label="Uptime" value={formatUptime(status?.uptime_s ?? 0)} />
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider flex items-center gap-1.5 mb-2">
          <Activity className="w-3.5 h-3.5" />
          <span>Publish rate by cadence tier</span>
        </div>
        <div className="space-y-1">
          {Object.entries(status?.msg_per_sec ?? {}).map(([tier, rate]) => (
            <div key={tier} className="flex items-center justify-between font-mono text-[11px]">
              <span className="text-[#64748B] dark:text-[#94A3B8]">{TIER_LABELS[tier] ?? tier}</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {rate.toFixed(2)} /s
                <span className="text-[#64748B] ml-2">({status?.per_tier[tier] ?? 0} signals)</span>
              </span>
            </div>
          ))}
          {Object.keys(status?.msg_per_sec ?? {}).length === 0 && (
            <div className="text-[11px] font-mono text-[#64748B]">Nothing is publishing.</div>
          )}
        </div>
      </div>
    </div>
  )
}
