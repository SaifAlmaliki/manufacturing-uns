/**
 * The /simulator console route (spec 7.1).
 *
 * Calls useSimulator once and passes the result down. Four panels each calling the hook
 * would mean four independent pollers on /status, and they would disagree with each other
 * on screen.
 */

import React, { useState } from 'react'
import { Cpu, Factory, Gauge, Sliders, Stethoscope } from 'lucide-react'
import { useSimulator } from '../../hooks/useSimulator'
import { PlantStateInspector } from './PlantStateInspector'
import { SignalInspector } from './SignalInspector'
import { SimulatorConfigPanel } from './SimulatorConfigPanel'
import { SimulatorDiagnosticsPanel } from './SimulatorDiagnosticsPanel'
import { SimulatorStatusPanel } from './SimulatorStatusPanel'

type SubTab = 'status' | 'configure' | 'plant' | 'diagnostics'

const SUB_TABS: Array<{ id: SubTab; label: string; icon: typeof Cpu }> = [
  { id: 'status', label: 'Status & Run Control', icon: Cpu },
  { id: 'configure', label: 'Configuration', icon: Sliders },
  { id: 'plant', label: 'Plant & Signals', icon: Factory },
  { id: 'diagnostics', label: 'Diagnostics', icon: Stethoscope },
]

export const SimulatorView: React.FC = () => {
  const simulator = useSimulator()
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('status')

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-3 md:px-4 py-2.5 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-2 shrink-0">
        <Gauge className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
        <div className="min-w-0">
          <h2 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider">
            Simulator Console
          </h2>
          <p className="text-[10px] font-mono text-[#64748B] dark:text-[#94A3B8] truncate">
            99_simulator — synthetic plant telemetry. Everything it publishes is simulated.
          </p>
        </div>
      </div>

      <div className="px-3 md:px-4 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center shrink-0 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-1 min-w-max">
          {SUB_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              id={`subtab-simulator-${id}`}
              onClick={() => setActiveSubTab(id)}
              className={`px-3 py-2.5 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
                activeSubTab === id
                  ? 'border-amber-500 dark:border-[#FFC107] text-amber-700 dark:text-[#FFC107]'
                  : 'border-transparent text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {activeSubTab === 'status' && <SimulatorStatusPanel simulator={simulator} />}
        {activeSubTab === 'configure' && <SimulatorConfigPanel simulator={simulator} />}
        {activeSubTab === 'plant' && (
          <>
            <PlantStateInspector simulator={simulator} />
            <SignalInspector simulator={simulator} />
          </>
        )}
        {activeSubTab === 'diagnostics' && <SimulatorDiagnosticsPanel simulator={simulator} />}
      </div>
    </div>
  )
}
