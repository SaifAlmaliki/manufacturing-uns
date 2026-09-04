/**
 * Live WTP snapshot from GET /simulator/plant: mode, filter, duty/lead pumps,
 * tank levels, flows and pressures. Polled, not reconstructed from MQTT events,
 * so a console opened mid-run sees what is true now.
 */

import React from 'react'
import { Droplets, Filter, Gauge, Waves } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'
import { CompactKpiRow, ConsoleCard, PageStat } from '../ui/console-ui'

const CHIP_EMERALD = 'text-emerald-400'
const CHIP_ORANGE = 'text-[#FF7A00]'
const ICON_EMERALD = 'bg-emerald-500/15'
const ICON_ORANGE = 'bg-[#FF7A00]/15'

function modeTone(value: string): { valueClassName: string; iconBg: string } {
  if (value === 'Backwash') {
    return { valueClassName: CHIP_ORANGE, iconBg: ICON_ORANGE }
  }
  if (value === 'Running' || value === 'InService') {
    return { valueClassName: CHIP_EMERALD, iconBg: ICON_EMERALD }
  }
  return { valueClassName: 'text-white', iconBg: 'bg-zinc-800' }
}

const MonoFigure: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5">
    <div className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</div>
    <div className="font-mono text-[11px] tabular-nums text-white">{value}</div>
  </div>
)

export const PlantStateInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, plant } = simulator
  const tick = (
    <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-[10px] tabular-nums text-zinc-400">
      tick {status?.tick_count ?? 0}
    </span>
  )

  if (!plant?.tanks) {
    return (
      <ConsoleCard padding="sm" className="text-center font-mono text-[11px] text-zinc-500">
        <div className="mb-2 flex items-center justify-end">{tick}</div>
        No plant state. The simulator is stopped, or no profile is loaded.
      </ConsoleCard>
    )
  }

  const modeChip = modeTone(plant.mode)
  const filterChip = modeTone(plant.filter_mode)

  return (
    <ConsoleCard padding="none" className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 px-3 py-2">
        <span className="font-mono text-[11px] font-bold text-white">
          {plant.enterprise} / {plant.site}
        </span>
        {tick}
      </div>

      <div className="border-b border-zinc-800 px-3 py-2">
        <CompactKpiRow>
          <PageStat
            compact
            label="Mode"
            value={plant.mode}
            valueClassName={modeChip.valueClassName}
            iconBg={modeChip.iconBg}
            icon={<Droplets className={`size-3.5 ${modeChip.valueClassName}`} />}
          />
          <PageStat
            compact
            label="Filter"
            value={plant.filter_mode}
            valueClassName={filterChip.valueClassName}
            iconBg={filterChip.iconBg}
            icon={<Filter className={`size-3.5 ${filterChip.valueClassName}`} />}
          />
          <PageStat
            compact
            label="Duty raw"
            value={plant.duty_raw_pump}
            icon={<Waves className="size-3.5 text-[#FF7A00]" />}
          />
          <PageStat
            compact
            label="Lead VFD"
            value={plant.lead_dist_pump}
            icon={<Gauge className="size-3.5 text-[#FF7A00]" />}
          />
        </CompactKpiRow>
      </div>

      <div className="grid grid-cols-3 gap-1.5 border-b border-zinc-800 px-3 py-2">
        {Object.entries(plant.tanks).map(([tag, tank]) => (
          <MonoFigure key={tag} label={tag} value={`${tank.level_pct.toFixed(1)} %`} />
        ))}
      </div>

      <div className="grid grid-cols-3 gap-1.5 px-3 py-2 xl:grid-cols-6">
        {Object.entries(plant.flows_m3h).map(([tag, value]) => (
          <MonoFigure key={tag} label={`${tag} m³/h`} value={value.toFixed(1)} />
        ))}
        {Object.entries(plant.pressures_barg).map(([tag, value]) => (
          <MonoFigure key={tag} label={`${tag} barg`} value={value.toFixed(2)} />
        ))}
      </div>
    </ConsoleCard>
  )
}
