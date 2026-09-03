import React, { useState } from 'react';
import { useTheme } from '../../context/ThemeContext';
import {
  GRAFANA_DASHBOARDS,
  GrafanaDashboardId,
  GrafanaEmbed,
} from '../common/GrafanaEmbed';
import { PageShell, PageContent, ConsoleCard, SegmentTabs } from '../ui/console-ui';
import { AuthenticationPanel } from './AuthenticationPanel';

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
      <PageContent fullWidth className="flex min-h-0 flex-1 flex-col gap-3 pb-3">
        <SegmentTabs
          tabs={tabs}
          active={dashboard}
          onChange={(id) => setDashboard(id as GrafanaDashboardId)}
        />
        <div className="shrink-0">
          <AuthenticationPanel />
        </div>
        <ConsoleCard padding="none" className="min-h-0 flex-1 overflow-hidden">
          <GrafanaEmbed uid={active.uid} theme={isDark ? 'dark' : 'light'} title={active.label} />
        </ConsoleCard>
      </PageContent>
    </PageShell>
  );
};
