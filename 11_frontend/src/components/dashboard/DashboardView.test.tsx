import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../context/UNSContext', () => {
  const t = Date.now();
  return {
  useUNS: () => ({
    allLoadedNodes: [{ topic: 'HalabjaWTP/P101' }],
    staleNodesCount: 0,
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

describe('DashboardView plant signal', () => {
  it('does not list edge/sim and shows one row per process tag', () => {
    render(
      <MemoryRouter>
        <DashboardView />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/edge \/ sim/i)).toBeNull();
    expect(screen.getByText('P101 / Current')).toBeTruthy();
    expect(screen.getByText('12.4')).toBeTruthy();
    expect(screen.getAllByText('P101 / Current')).toHaveLength(1);
  });

  it('does not pretend operational targets are 100% when there is nothing to measure', () => {
    render(
      <MemoryRouter>
        <DashboardView />
      </MemoryRouter>,
    );
    expect(screen.getByText('No rules configured')).toBeTruthy();
    expect(screen.getByText('Clear')).toBeTruthy();
    expect(screen.queryByText('Alarm Acknowledgement')).toBeNull();
  });

  it('labels activity as a one-minute live window', () => {
    render(
      <MemoryRouter>
        <DashboardView />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Live · 60s/)).toBeTruthy();
    expect(screen.getByText(/2 process msgs · last 60s/)).toBeTruthy();
  });
});
