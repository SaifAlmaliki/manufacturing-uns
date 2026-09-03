/**
 * The PackML state of every line, per site, with the ambient conditions, shift and tariff
 * that drive it (spec 7.2).
 *
 * The ambient block is not decoration. It is the shared input every utility signal in plan
 * A is derived from — chiller load follows wet-bulb, compressor efficiency follows ambient
 * temperature, and the energy cost follows the tariff. Showing them beside the line states
 * is what makes "why did power jump at 14:00?" answerable from one screen.
 *
 * Read from the polled /plant snapshot rather than accumulated from the MQTT transition
 * events. The events say what changed; the snapshot says what is true, including for a
 * console that was opened after the transition happened.
 */

import React from 'react'
import type { SimulatorState } from './SimulatorStatusPanel'
import { ConsoleCard } from '../ui/console-ui'

/**
 * PackML's states, coloured by what an operator would do about them. Execute is green,
 * Held and Aborted are red, and everything in between is a transition worth noticing but
 * not worth alarming about.
 */
const STATE_STYLES: Record<string, string> = {
  Execute: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  Idle: 'bg-zinc-800 text-zinc-400 border-zinc-700',
  Starting: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  Completing: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  Complete: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  Holding: 'bg-[#FF7A00]/10 text-[#FF7A00] border-[#FF7A00]/30',
  Held: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
  Aborted: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
  Stopped: 'bg-zinc-800 text-zinc-400 border-zinc-700',
}

function stateStyle(state: string): string {
  return STATE_STYLES[state] ?? STATE_STYLES.Idle
}

function formatSeconds(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  return minutes > 0 ? `${minutes}m ${total % 60}s` : `${total}s`
}

/** Tariff, coloured by cost, because the peak window is the one worth noticing. */
const TARIFF_STYLES: Record<string, string> = {
  peak: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
  shoulder: 'bg-[#FF7A00]/10 text-[#FF7A00] border-[#FF7A00]/30',
  off_peak: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
}

const Ambient: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5">
    <div className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</div>
    <div className="font-mono text-[11px] tabular-nums text-white">{value}</div>
  </div>
)

export const PlantStateInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, plant } = simulator
  const sites = Object.entries(plant?.sites ?? {})

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-end">
        <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-[10px] tabular-nums text-zinc-400">
          tick {status?.tick_count ?? 0}
        </span>
      </div>

      {sites.length === 0 && (
        <ConsoleCard padding="sm" className="text-center font-mono text-[11px] text-zinc-500">
          No plant state. The simulator is stopped, or no profile is loaded.
        </ConsoleCard>
      )}

      {sites.map(([site, siteState]) => (
        <ConsoleCard key={site} padding="none" className="overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-zinc-800 px-3 py-2">
            <span className="font-mono text-[11px] font-bold text-white">{site}</span>
            <div className="flex items-center gap-1.5">
              <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-[9px] uppercase text-zinc-400">
                shift {siteState.shift}
              </span>
              <span
                className={`rounded border px-2 py-0.5 font-mono text-[9px] font-bold uppercase ${
                  TARIFF_STYLES[siteState.tariff] ?? TARIFF_STYLES.shoulder
                }`}
              >
                {siteState.tariff.replace('_', ' ')}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-1.5 border-b border-zinc-800 px-3 py-2 xl:grid-cols-6">
            <Ambient label="Ambient" value={`${siteState.ambient_temp_c.toFixed(1)} °C`} />
            <Ambient label="Humidity" value={`${siteState.ambient_rh_pct.toFixed(0)} %`} />
            <Ambient label="Wet bulb" value={`${siteState.wet_bulb_temp_c.toFixed(1)} °C`} />
            <Ambient label="Wind" value={`${siteState.wind_speed_ms.toFixed(1)} m/s`} />
            <Ambient label="Pressure" value={`${siteState.barometric_mbar.toFixed(0)} mbar`} />
            <Ambient label="Grid CO₂" value={`${siteState.grid_co2_g_per_kwh.toFixed(0)} g/kWh`} />
          </div>

          <table className="w-full font-mono text-[11px]">
            <thead className="text-[9px] uppercase text-zinc-500">
              <tr className="border-b border-zinc-800">
                <th className="px-3 py-1.5 text-left">Line</th>
                <th className="px-3 py-1.5 text-left">PackML state</th>
                <th className="px-3 py-1.5 text-left">Previous</th>
                <th className="px-3 py-1.5 text-right">Rate</th>
                <th className="px-3 py-1.5 text-right">Throughput</th>
                <th className="px-3 py-1.5 text-right">Heat load</th>
                <th className="px-3 py-1.5 text-right">Air demand</th>
                <th className="px-3 py-1.5 text-right">Time in state</th>
                <th className="px-3 py-1.5 text-right">Transitions</th>
              </tr>
            </thead>
            <tbody className="text-white">
              {Object.entries(siteState.lines).map(([line, lineState]) => (
                <tr key={line} className="border-b border-zinc-800/60">
                  <td className="px-3 py-1.5">{line}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`rounded border px-2 py-0.5 text-[9px] font-bold uppercase ${stateStyle(lineState.state)}`}
                    >
                      {lineState.state}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-zinc-400">{lineState.previous ?? '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {(lineState.production_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {lineState.throughput_tph.toFixed(1)} t/h
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">
                    {lineState.heat_load.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">
                    {lineState.air_demand.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">
                    {formatSeconds(lineState.time_in_state_s)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-400">
                    {lineState.transition_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ConsoleCard>
      ))}
    </div>
  )
}
