import React from 'react';

export const GRAFANA_DASHBOARDS = {
  platform: {
    uid: 'uns-platform-observability',
    label: 'Platform',
  },
  process: {
    uid: 'uns-process-visualization',
    label: 'Process',
  },
  oee: {
    uid: 'uns-oee',
    label: 'OEE',
  },
} as const;

export type GrafanaDashboardId = keyof typeof GRAFANA_DASHBOARDS;

export function grafanaKioskPath(uid: string, theme: 'dark' | 'light'): string {
  return `/grafana/d/${uid}?kiosk&theme=${theme}`;
}

interface GrafanaEmbedProps {
  uid: string;
  theme: 'dark' | 'light';
  title: string;
}

export const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({ uid, theme, title }) => {
  const src = grafanaKioskPath(uid, theme);
  return (
    <iframe
      title={title}
      src={src}
      className="w-full h-full min-h-0 border-0 bg-[#111114]"
      referrerPolicy="same-origin"
    />
  );
};
