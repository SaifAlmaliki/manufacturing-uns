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
import { Factory } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'

/**
 * PackML's states, coloured by what an operator would do about them. Execute is green,
 * Held and Aborted are red, and everything in between is a transition worth noticing but
 * not worth alarming about.
 */
const STATE_STYLES: Record<string, string> = {
  Execute: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
  Idle: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
  Starting: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Completing: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Complete: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Holding: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  Held: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  Aborted: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  Stopped: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
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
  peak: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  shoulder: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  off_peak: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
}

const Ambient: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="px-2 py-1.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
    <div className="text-[9px] text-[#64748B] uppercase tracking-wider">{label}</div>
    <div className="text-[11px] font-mono tabular-nums text-[#0F172A] dark:text-[#F8FAFC]">{value}</div>
  </div>
)

export const PlantStateInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, plant } = simulator
  const sites = Object.entries(plant?.sites ?? {})

  return (
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
          <Factory className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
          <span>Plant State</span>
        </h3>
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px] tabular-nums">
          tick {status?.tick_count ?? 0}
        </span>
      </div>

      {sites.length === 0 && (
        <div className="p-4 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#64748B] text-center">
          No plant state. The simulator is stopped, or no profile is loaded.
        </div>
      )}

      {sites.map(([site, siteState]) => (
        <div
          key={site}
          className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden"
        >
          <div className="px-3 py-2 border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between gap-2">
            <span className="font-mono text-[11px] font-bold text-[#0F172A] dark:text-[#F8FAFC]">{site}</span>
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[9px] uppercase">
                shift {siteState.shift}
              </span>
              <span
                className={`px-2 py-0.5 rounded border font-mono text-[9px] font-bold uppercase ${
                  TARIFF_STYLES[siteState.tariff] ?? TARIFF_STYLES.shoulder
                }`}
              >
                {siteState.tariff.replace('_', ' ')}
              </span>
            </div>
          </div>

          <div className="px-3 py-2 grid grid-cols-3 xl:grid-cols-6 gap-1.5 border-b border-[#E2E8F0] dark:border-[#1E293B]">
            <Ambient label="Ambient" value={`${siteState.ambient_temp_c.toFixed(1)} °C`} />
            <Ambient label="Humidity" value={`${siteState.ambient_rh_pct.toFixed(0)} %`} />
            <Ambient label="Wet bulb" value={`${siteState.wet_bulb_temp_c.toFixed(1)} °C`} />
            <Ambient label="Wind" value={`${siteState.wind_speed_ms.toFixed(1)} m/s`} />
            <Ambient label="Pressure" value={`${siteState.barometric_mbar.toFixed(0)} mbar`} />
            <Ambient label="Grid CO₂" value={`${siteState.grid_co2_g_per_kwh.toFixed(0)} g/kWh`} />
          </div>

          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Line</th>
                <th className="text-left px-3 py-1.5">PackML state</th>
                <th className="text-left px-3 py-1.5">Previous</th>
                <th className="text-right px-3 py-1.5">Rate</th>
                <th className="text-right px-3 py-1.5">Throughput</th>
                <th className="text-right px-3 py-1.5">Heat load</th>
                <th className="text-right px-3 py-1.5">Air demand</th>
                <th className="text-right px-3 py-1.5">Time in state</th>
                <th className="text-right px-3 py-1.5">Transitions</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {Object.entries(siteState.lines).map(([line, lineState]) => (
                <tr key={line} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5">{line}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`px-2 py-0.5 rounded border text-[9px] font-bold uppercase ${stateStyle(lineState.state)}`}
                    >
                      {lineState.state}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.previous ?? '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {(lineState.production_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {lineState.throughput_tph.toFixed(1)} t/h
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.heat_load.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.air_demand.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {formatSeconds(lineState.time_in_state_s)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.transition_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
