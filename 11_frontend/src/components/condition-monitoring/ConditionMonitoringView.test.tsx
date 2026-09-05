import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { UnsNode } from '../../types/uns';

const getConnectivityServers = vi.hoisted(() => vi.fn());
const getHistoricEvents = vi.hoisted(() => vi.fn());
const subscribeMqttMessages = vi.hoisted(() => vi.fn());

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getConnectivityServers, getHistoricEvents, subscribeMqttMessages },
}));

const uns = vi.hoisted(() => ({
  selectedNode: null as UnsNode | null,
}));
vi.mock('../../context/UNSContext', () => ({ useUNS: () => uns }));
vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ activeAlarms: [] }),
}));

const auth = vi.hoisted(() => ({
  hasPermission: (feature: string): boolean => feature === 'uns_tree',
  isAdmin: true,
  roles: ['admin'] as ('admin' | 'operator')[],
  currentUser: null as null,
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

vi.mock('../home/UnsTreeView', () => ({
  UnsTreeView: () => <div>Namespace Tree</div>,
}));

import { ConditionMonitoringView } from './ConditionMonitoringView';

const FAULT = {
  serverId: 's1',
  nodeId: 'n1',
  browsePath: 'Distribution/P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/Distribution/P201/Fault',
  subscribed: true,
};
const SPEED = {
  serverId: 's1',
  nodeId: 'n2',
  browsePath: 'Distribution/P202/Speed',
  displayName: 'Speed',
  mqttTopic: 'Server/OpcPlc/Distribution/P202/Speed',
  subscribed: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  uns.selectedNode = null;
  auth.hasPermission = (feature: string): boolean => feature === 'uns_tree';
  getConnectivityServers.mockResolvedValue([
    {
      id: 's1',
      name: 'wtp',
      protocol: 'OPC_UA',
      endpoint: 'opc.tcp://x',
      lastStatus: 'connected',
      lastError: '',
      tags: [FAULT, SPEED, { ...FAULT, nodeId: 'n3', subscribed: false, displayName: 'Ignored' }],
    },
  ]);
  getHistoricEvents.mockResolvedValue([]);
  subscribeMqttMessages.mockReturnValue(() => undefined);
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ConditionMonitoringView />
    </MemoryRouter>,
  );
}

describe('ConditionMonitoringView catalog', () => {
  it('shows AccessRestricted when uns_tree is denied', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    renderPage();
    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getConnectivityServers).not.toHaveBeenCalled();
  });

  it('shows a catalog error without the empty-subscribe copy', async () => {
    getConnectivityServers.mockRejectedValue(new Error('column missing'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/column missing/i)).toBeTruthy());
    expect(screen.queryByText(/subscribe tags in assets/i)).toBeNull();
  });

  it('shows the subscribe empty state when the catalog has no subscribed tags', async () => {
    getConnectivityServers.mockResolvedValue([
      {
        id: 's1',
        name: 'wtp',
        protocol: 'OPC_UA',
        endpoint: 'x',
        lastStatus: 'untested',
        lastError: '',
        tags: [],
      },
    ]);
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText(
          (_content, el) =>
            el?.tagName === 'P' &&
            /subscribe tags in assets & connectivity/i.test(el.textContent ?? ''),
        ),
      ).toBeTruthy(),
    );
    expect(screen.getByRole('link', { name: /assets & connectivity/i })).toHaveAttribute(
      'href',
      '/connectivity',
    );
  });

  it('renders one card per subscribed tag and hides All signals until scoped', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    expect(screen.getByText('Speed')).toBeTruthy();
    expect(screen.queryByText('Ignored')).toBeNull();
    expect(screen.queryByRole('button', { name: /all signals/i })).toBeNull();
  });

  it('scopes to a loaded P201 node and All signals restores both cards', async () => {
    uns.selectedNode = {
      topic: 'AcmeWater/Site1/Distribution/Train1/P201',
      name: 'P201',
      lastUpdated: '',
      isLeaf: true,
      children: [],
    };
    renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    expect(screen.queryByText('Speed')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /all signals/i }));
    expect(screen.getByText('Speed')).toBeTruthy();
    expect(screen.getByText('Fault')).toBeTruthy();
  });

  it('shows zone empty copy when the scoped node has no subscribed tags', async () => {
    uns.selectedNode = {
      topic: 'AcmeWater/Site1/Distribution/Train1/P999',
      name: 'P999',
      lastUpdated: '',
      isLeaf: true,
      children: [],
    };
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('No subscribed signals in this zone.')).toBeTruthy(),
    );
    expect(screen.getByRole('button', { name: /all signals/i })).toBeTruthy();
    expect(screen.queryByText(/subscribe tags in assets/i)).toBeNull();
  });

  it('shows search empty copy when nothing matches', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzz' } });
    expect(screen.getByText('No signals match this search.')).toBeTruthy();
    expect(screen.queryByText('Fault')).toBeNull();
  });
});
