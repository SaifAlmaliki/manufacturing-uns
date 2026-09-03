/**
 * The /simulator console route (spec 7.1).
 */

import React, { useState } from 'react';
import { Cpu, Factory, Sliders, Stethoscope } from 'lucide-react';
import { useSimulator } from '../../hooks/useSimulator';
import { PlantStateInspector } from './PlantStateInspector';
import { SignalInspector } from './SignalInspector';
import { SimulatorConfigPanel } from './SimulatorConfigPanel';
import { SimulatorDiagnosticsPanel } from './SimulatorDiagnosticsPanel';
import { SimulatorStatusPanel } from './SimulatorStatusPanel';
import { PageShell, PageContent, SegmentTabs } from '../ui/console-ui';

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
    <PageShell id="simulator-view" scroll={false} className="flex flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <SegmentTabs tabs={SUB_TABS} active={activeSubTab} onChange={(id) => setActiveSubTab(id as SubTab)} />

          {activeSubTab === 'status' && <SimulatorStatusPanel simulator={simulator} />}
          {activeSubTab === 'configure' && <SimulatorConfigPanel simulator={simulator} />}
          {activeSubTab === 'plant' && (
            <div className="flex flex-col gap-3">
              <PlantStateInspector simulator={simulator} />
              <SignalInspector simulator={simulator} />
            </div>
          )}
          {activeSubTab === 'diagnostics' && <SimulatorDiagnosticsPanel simulator={simulator} />}
        </PageContent>
      </div>
    </PageShell>
  );
};
