/**
 * The /simulator console route (spec 7.1).
 */

import React, { useState } from 'react';
import { Cpu, Factory, Gauge, Sliders, Stethoscope } from 'lucide-react';
import { useSimulator } from '../../hooks/useSimulator';
import { PlantStateInspector } from './PlantStateInspector';
import { SignalInspector } from './SignalInspector';
import { SimulatorConfigPanel } from './SimulatorConfigPanel';
import { SimulatorDiagnosticsPanel } from './SimulatorDiagnosticsPanel';
import { SimulatorStatusPanel } from './SimulatorStatusPanel';
import { PageShell, PageContent, ConsoleCard, SegmentTabs } from '../ui/console-ui';

type SubTab = 'status' | 'configure' | 'plant' | 'diagnostics';

const SUB_TABS = [
  { id: 'status' as const, label: 'Status & Control', icon: Cpu },
  { id: 'configure' as const, label: 'Configuration', icon: Sliders },
  { id: 'plant' as const, label: 'Plant & Signals', icon: Factory },
  { id: 'diagnostics' as const, label: 'Diagnostics', icon: Stethoscope },
];

export const SimulatorView: React.FC = () => {
  const simulator = useSimulator();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('status');

  return (
    <PageShell scroll={false} className="flex flex-col">
      <PageContent className="shrink-0 space-y-4 pb-4">
        <ConsoleCard className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#FF7A00]/15">
              <Gauge className="size-5 text-[#FF7A00]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Simulator</h2>
              <p className="mt-0.5 text-sm text-zinc-500">
                Synthetic plant telemetry generator — everything published here is simulated.
              </p>
            </div>
          </div>
          <SegmentTabs tabs={SUB_TABS} active={activeSubTab} onChange={(id) => setActiveSubTab(id as SubTab)} />
        </ConsoleCard>
      </PageContent>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 md:px-6 md:pb-6">
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
    </PageShell>
  );
};
