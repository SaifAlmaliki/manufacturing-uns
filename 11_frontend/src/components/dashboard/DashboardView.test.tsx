import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const plantSummary = vi.hoisted(() => ({
  connectivity: { serverCount: 1, signalCount: 12 } as { serverCount: number; signalCount: number } | null,
  signals: [
    {
      serverId: 's1',
      serverName: 'wtp2',
      nodeId: 'ns=3;s=P101',
      browsePath: 'P101/Current',
      displayName: 'Motor current',
      mqttTopic: 'HalabjaWTP/P101/Current',
      subscribed: true,
      unitOfMeasure: 'A',
    },
  ],
  loading: false,
}));

vi.mock('../../lib/dashboard/useDashboardPlantSummary', () => ({
  useDashboardPlantSummary: () => plantSummary,
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    hasPermission: (feature: string) => feature === 'connectivity',
  }),
}));

vi.mock('../../context/UNSContext', () => {
  const t = Date.now();
  return {
    useUNS: () => ({
      allLoadedNodes: [{ topic: 'HalabjaWTP/P101' }],
      staleNodesCount: 0,
      bookmarks: [],
      jumpToTopicInTree: vi.fn(),
      mqttFeed: [
        {
          id: 'sim',
          topic: 'HalabjaWTP/edge/sim',
          payload: { value: 1 },
          timestamp: new Date(t - 500).toISOString(),
        },
        {
          id: 'p101-new',
          topic: 'HalabjaWTP/P101/Current',
          payload: { value: 12.4 },
          timestamp: new Date(t - 1_000).toISOString(),
        },
        {
          id: 'p101-old',
          topic: 'HalabjaWTP/P101/Current',
          payload: { value: 11 },
          timestamp: new Date(t - 4_000).toISOString(),
        },
      ],
      health: {
        status: 'LIVE',
        graphqlHttp: true,
        graphqlWs: true,
        mode: 'LIVE_GRAPHQL',
        lastPingMs: 40,
      },
    }),
  };
});
vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({
    totalUnacknowledgedCount: 0,
    activeAlarms: [],
    rules: [],
    isPlatformLive: true,
  }),
}));

import { DashboardView } from './DashboardView';

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardView />
    </MemoryRouter>,
  );
}

describe('DashboardView plant signal', () => {
  it('does not list edge/sim and shows one row per process tag', () => {
    renderDashboard();
    expect(screen.queryByText(/edge \/ sim/i)).toBeNull();
    expect(screen.getByText('Motor current')).toBeTruthy();
    expect(screen.getAllByText('12.4').length).toBeGreaterThan(0);
    expect(screen.getAllByText('P101 / Current').length).toBeGreaterThan(0);
  });

  it('does not pretend operational targets are 100% when there is nothing to measure', () => {
    renderDashboard();
    expect(screen.getByText('No rules configured')).toBeTruthy();
    expect(screen.getByText('Clear')).toBeTruthy();
    expect(screen.queryByText('Alarm Acknowledgement')).toBeNull();
  });

  it('labels activity as a one-minute live window', () => {
    renderDashboard();
    expect(screen.getByText(/Live · 60s/)).toBeTruthy();
    expect(screen.getByText(/2 process msgs · last 60s/)).toBeTruthy();
  });

  it('routes quick actions to condition monitoring instead of the retired tree route', () => {
    renderDashboard();
    expect(screen.getAllByRole('button', { name: /Condition Monitoring/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /^Tree$/i })).toBeNull();
  });

  it('shows connectivity and subscribed signal counts when catalog data is available', () => {
    renderDashboard();
    expect(screen.getByText(/1 OPC UA server · 12 subscribed signals/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Open signals/i })).toBeTruthy();
  });

  it('shows a signal snapshot card from subscribed catalog tags', () => {
    renderDashboard();
    expect(screen.getByText('Motor current')).toBeTruthy();
    expect(screen.getAllByText('12.4').length).toBeGreaterThan(0);
  });
});
