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

export interface GrafanaEmbedOptions {
  vars?: Record<string, string>;
  from?: string;
  to?: string;
}

export function grafanaTopicFilter(topic: string): string {
  return topic.replace(/\/[# +]+$/g, '').replace(/#$/, '').trim();
}

export function grafanaRangeFromPreset(preset: string): { from: string; to: string } {
  const fromByPreset: Record<string, string> = {
    '5m': 'now-5m',
    '15m': 'now-15m',
    '1h': 'now-1h',
    '6h': 'now-6h',
    '24h': 'now-24h',
    all: 'now-30d',
  };
  return { from: fromByPreset[preset] ?? 'now-6h', to: 'now' };
}

export function grafanaKioskPath(
  uid: string,
  theme: 'dark' | 'light',
  options: GrafanaEmbedOptions = {},
): string {
  const params = new URLSearchParams();
  params.set('kiosk', '');
  params.set('theme', theme);
  if (options.from) params.set('from', options.from);
  if (options.to) params.set('to', options.to);
  for (const [name, value] of Object.entries(options.vars ?? {})) {
    params.set(`var-${name}`, value);
  }
  return `/grafana/d/${uid}?${params.toString()}`;
}

interface GrafanaEmbedProps extends GrafanaEmbedOptions {
  uid: string;
  theme: 'dark' | 'light';
  title: string;
  className?: string;
}

export const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({
  uid,
  theme,
  title,
  vars,
  from,
  to,
  className = 'w-full h-full min-h-0 border-0 bg-[#111114]',
}) => {
  const src = grafanaKioskPath(uid, theme, { vars, from, to });
  return (
    <iframe
      title={title}
      src={src}
      className={className}
      referrerPolicy="same-origin"
    />
  );
};
