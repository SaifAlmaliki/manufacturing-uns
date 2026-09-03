import React, { useState } from 'react';

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
  params.set('kiosk', '1');
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
  const [signedOut, setSignedOut] = useState(false);

  /**
   * Grafana is not anonymous any more, and an iframe cannot report an HTTP status — `load`
   * fires for a sign-in page as readily as for a dashboard. What it can report is *where it
   * ended up*, because nginx serves /grafana from the console's own origin.
   *
   * A path under /login means Grafana's OIDC round trip did not complete inside the frame,
   * usually because the browser is blocking something about a redirect chain in third-party
   * context. The answer is a full-page link, where the same redirect can succeed.
   */
  const checkWhereItLanded = (event: React.SyntheticEvent<HTMLIFrameElement>) => {
    try {
      const path = event.currentTarget.contentWindow?.location?.pathname ?? '';
      setSignedOut(path.includes('/login'));
    } catch {
      setSignedOut(false);
    }
  };

  return (
    <div className="relative w-full h-full min-h-0">
      <iframe
        title={title}
        src={src}
        className={className}
        referrerPolicy="same-origin"
        onLoad={checkWhereItLanded}
      />
      {signedOut && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#111114]/95 text-center px-6">
          <p className="text-xs font-bold text-[#F8FAFC]">Grafana needs its own sign-in</p>
          <p className="text-[11px] text-[#94A3B8] max-w-md">
            The dashboards are served by Grafana, which signs in against the same Keycloak realm
            as this console. It could not complete that inside this panel.
          </p>
          <a
            href="/grafana/"
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 rounded bg-[#FFC107] text-[#0F172A] text-[11px] font-bold uppercase tracking-wider"
          >
            Sign in to Grafana
          </a>
        </div>
      )}
    </div>
  );
};
