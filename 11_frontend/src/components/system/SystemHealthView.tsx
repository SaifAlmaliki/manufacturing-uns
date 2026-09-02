import React, { useState } from 'react';
import { Activity } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import {
  GRAFANA_DASHBOARDS,
  GrafanaDashboardId,
  GrafanaEmbed,
} from '../common/GrafanaEmbed';

export const SystemHealthView: React.FC = () => {
  const { isDark } = useTheme();
  const [dashboard, setDashboard] = useState<GrafanaDashboardId>('platform');
  const active = GRAFANA_DASHBOARDS[dashboard];

  return (
    <div
      id="system-health-view"
      className="flex-1 min-h-0 flex flex-col overflow-hidden bg-[#050505] text-[#F8FAFC] font-mono text-xs"
    >
      <div className="flex items-center justify-between px-6 py-3 border-b border-[#1E293B] shrink-0 gap-4">
        <div>
          <h1 className="text-sm font-bold text-[#F8FAFC] uppercase tracking-wider flex items-center gap-2">
            <Activity className="w-4 h-4 text-[#FFC107]" />
            <span>System Health &amp; Grafana</span>
          </h1>
          <p className="text-[10px] text-[#64748B] mt-1">
            Process Visualization, OEE, and Platform Observability — Grafana, inside the console.
          </p>
        </div>
        <div className="flex items-center gap-1 p-0.5 rounded bg-[#111114] border border-[#1E293B]">
          {(Object.keys(GRAFANA_DASHBOARDS) as GrafanaDashboardId[]).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setDashboard(id)}
              className={`px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider ${
                dashboard === id
                  ? 'bg-[#FFC107] text-[#0F172A]'
                  : 'text-[#94A3B8] hover:text-[#F8FAFC]'
              }`}
            >
              {GRAFANA_DASHBOARDS[id].label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <GrafanaEmbed uid={active.uid} theme={isDark ? 'dark' : 'light'} title={active.label} />
      </div>
    </div>
  );
};
