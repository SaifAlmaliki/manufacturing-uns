/**
 * What the simulator is doing right now, and the four buttons that change it (spec 7.1).
 *
 * Every number here comes from the polled /status body. Nothing is derived, accumulated or
 * remembered locally: a console that counted messages itself would drift from the
 * simulator within minutes and there would be no way to tell which of the two was right.
 */

import React from 'react'
import { Activity, AlertTriangle, Cpu, Lock, Pause, Play, Radio, RotateCcw, Square, Timer, WifiOff, XCircle } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { useSimulator } from '../../hooks/useSimulator'
import type { RunAction, RunState } from '../../types/simulator'
import { BtnGhost, BtnPrimary, CompactKpiRow, ConsoleCard, PageStat } from '../ui/console-ui'

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
  running: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  paused: 'bg-[#FF7A00]/10 text-[#FF7A00] border-[#FF7A00]/30',
  starting: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  stopped: 'bg-zinc-800 text-zinc-400 border-zinc-700',
}

function formatUptime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m ${total % 60}s`
}

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
  const failed = status?.failed_total ?? 0

  return (
    <div className="flex flex-col gap-3">
      {offline && (
        <div className="flex items-start gap-2 rounded-lg border border-zinc-700 bg-[#111114] px-3 py-2">
          <WifiOff className="mt-0.5 size-4 shrink-0 text-rose-400" />
          <div className="font-mono text-[11px] text-zinc-400">
            <div className="font-bold text-white">No simulator is answering on /simulator</div>
            <div className="mt-0.5">
              The simulator is optional. If one should be running, check that 99_simulator is up and
              that port 8099 is reachable. Values below are the last that were read.
            </div>
          </div>
        </div>
      )}

      {status?.overrides_active && (
        <div className="flex items-start gap-2 rounded-lg border border-[#FF7A00]/30 bg-[#FF7A00]/10 px-3 py-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[#FF7A00]" />
          <div className="font-mono text-[11px] text-[#FF7A00]">
            <span className="font-bold">Runtime overrides are active.</span> The running plant no longer
            matches the profile files on disk, and nothing here is written back to them. A restart
            returns the simulator to <code>conf/simulator/</code>.
          </div>
        </div>
      )}

      {lastError && lastError.kind === 'http' && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 font-mono text-[11px] text-rose-400">
          {lastError.field ? `${lastError.field}: ${lastError.message}` : lastError.message}
        </div>
      )}

      <CompactKpiRow
        actions={
          <>
            <span
              className={`rounded border px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-wider ${RUN_STATE_STYLES[runState]}`}
            >
              {runState}
            </span>
            <span className="rounded-lg border border-zinc-800 bg-zinc-900/80 px-2 py-1 text-xs text-[#FF7A00]">
              profile: {status?.profile ?? '—'}
            </span>
            <span className="rounded-lg border border-zinc-800 bg-zinc-900/80 px-2 py-1 text-xs text-[#FF7A00]">
              seed: {status?.seed ?? '—'}
            </span>
            {!canControl && (
              <span className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-[9px] text-zinc-400">
                <Lock className="size-3 text-rose-400" />
                Read-Only
              </span>
            )}
            {actions.map(({ action, label, icon: Icon, enabledIn }) => {
              const disabled = !canControl || busy || offline || !enabledIn.includes(runState)
              const Button = disabled ? BtnGhost : BtnPrimary
              return (
                <Button
                  key={action}
                  id={`simulator-run-${action}`}
                  disabled={disabled}
                  onClick={() => void run(action)}
                  title={canControl ? label : 'Requires the Simulator Control permission'}
                  className="px-2.5 py-1.5 text-xs"
                >
                  <Icon className="size-3.5" />
                  {label}
                </Button>
              )
            })}
          </>
        }
      >
        <PageStat compact label="Devices" value={status?.device_count ?? 0} icon={<Cpu className="size-3.5 text-[#FF7A00]" />} />
        <PageStat compact label="Signals" value={status?.signal_count ?? 0} icon={<Radio className="size-3.5 text-[#FF7A00]" />} />
        <PageStat compact label="Msg / sec" value={totalRate.toFixed(1)} icon={<Activity className="size-3.5 text-[#FF7A00]" />} />
        <PageStat compact label="Published" value={(status?.published_total ?? 0).toLocaleString()} icon={<Activity className="size-3.5 text-zinc-400" />} iconBg="bg-zinc-800" />
        <PageStat
          compact
          label="Failed"
          value={failed.toLocaleString()}
          valueClassName={failed > 0 ? 'text-rose-400' : 'text-white'}
          icon={<XCircle className={`size-3.5 ${failed > 0 ? 'text-rose-400' : 'text-zinc-500'}`} />}
          iconBg={failed > 0 ? 'bg-rose-500/15' : 'bg-zinc-800'}
        />
        <PageStat compact label="Uptime" value={formatUptime(status?.uptime_s ?? 0)} icon={<Timer className="size-3.5 text-zinc-400" />} iconBg="bg-zinc-800" />
      </CompactKpiRow>

      <ConsoleCard padding="sm">
        <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
          <Activity className="size-3.5" />
          <span>Publish rate by cadence tier</span>
        </div>
        <div className="space-y-1">
          {Object.entries(status?.msg_per_sec ?? {}).map(([tier, rate]) => (
            <div key={tier} className="flex items-center justify-between text-sm">
              <span className="text-zinc-500">{TIER_LABELS[tier] ?? tier}</span>
              <span className="tabular-nums text-[#FF7A00]">
                {rate.toFixed(2)} /s
                <span className="ml-2 text-zinc-600">({status?.per_tier[tier] ?? 0} signals)</span>
              </span>
            </div>
          ))}
          {Object.keys(status?.msg_per_sec ?? {}).length === 0 && (
            <div className="text-sm text-zinc-500">Nothing is publishing.</div>
          )}
        </div>
      </ConsoleCard>
    </div>
  )
}
