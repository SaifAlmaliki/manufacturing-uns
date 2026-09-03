import React, { useState } from 'react';
import { Activity } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import {
  GRAFANA_DASHBOARDS,
  GrafanaDashboardId,
  GrafanaEmbed,
} from '../common/GrafanaEmbed';
import { PageShell, PageContent, ConsoleCard, SegmentTabs } from '../ui/console-ui';

export const SystemHealthView: React.FC = () => {
  const { isDark } = useTheme();
  const [dashboard, setDashboard] = useState<GrafanaDashboardId>('platform');
  const active = GRAFANA_DASHBOARDS[dashboard];

  const tabs = (Object.keys(GRAFANA_DASHBOARDS) as GrafanaDashboardId[]).map((id) => ({
    id,
    label: GRAFANA_DASHBOARDS[id].label,
  }));

  return (
    <PageShell id="system-health-view" scroll={false} className="flex flex-col">
      <PageContent className="flex shrink-0 flex-col gap-4 pb-0">
        <ConsoleCard className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#FF7A00]/15">
              <Activity className="size-5 text-[#FF7A00]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">System Health</h2>
              <p className="mt-0.5 text-sm text-zinc-500">
                Platform observability, process visualization, and OEE — Grafana embedded in the console.
              </p>
            </div>
          </div>
          <SegmentTabs tabs={tabs} active={dashboard} onChange={(id) => setDashboard(id as GrafanaDashboardId)} />
        </ConsoleCard>
      </PageContent>

      <div className="min-h-0 flex-1 px-4 pb-4 md:px-6 md:pb-6">
        <ConsoleCard padding="none" className="h-full overflow-hidden">
          <GrafanaEmbed uid={active.uid} theme={isDark ? 'dark' : 'light'} title={active.label} />
        </ConsoleCard>
      </div>
    </PageShell>
  );
};
