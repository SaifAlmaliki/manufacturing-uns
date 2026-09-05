import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getConnectivityServers = vi.hoisted(() => vi.fn());
const saveConnectivityServer = vi.hoisted(() => vi.fn());
const deleteConnectivityServer = vi.hoisted(() => vi.fn());
const testOpcUaConnection = vi.hoisted(() => vi.fn());
const browseOpcUa = vi.hoisted(() => vi.fn());
const discoverOpcUaVariables = vi.hoisted(() => vi.fn());
const subscribeOpcUaVariables = vi.hoisted(() => vi.fn());
const readOpcUaNodes = vi.hoisted(() => vi.fn());
const updateConnectivityTagTopic = vi.hoisted(() => vi.fn());
const unsubscribeConnectivityTag = vi.hoisted(() => vi.fn());
const subscribeOpcUaDataChanges = vi.hoisted(() => vi.fn());

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getConnectivityServers,
    saveConnectivityServer,
    deleteConnectivityServer,
    testOpcUaConnection,
    browseOpcUa,
    discoverOpcUaVariables,
    subscribeOpcUaVariables,
    readOpcUaNodes,
    updateConnectivityTagTopic,
    unsubscribeConnectivityTag,
    subscribeOpcUaDataChanges,
  },
}));

const auth = vi.hoisted(() => ({
  hasPermission: (feature: string): boolean => feature === 'connectivity',
  isAdmin: true,
  roles: ['admin'] as ('admin' | 'operator')[],
  currentUser: null as null,
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

import { ConnectivityView } from './ConnectivityView';

const SERVER = {
  id: 's1',
  name: 'opcplc',
  protocol: 'opc_ua',
  endpoint: 'opc.tcp://desktop-h4hdql2:50000/',
  lastStatus: 'untested',
  lastError: '',
  lastTestedAt: null,
  tags: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.hasPermission = (feature: string): boolean => feature === 'connectivity';
  auth.isAdmin = true;
  auth.roles = ['admin'];
  getConnectivityServers.mockResolvedValue([SERVER]);
  saveConnectivityServer.mockImplementation(async (input) => ({
    ...SERVER,
    ...input,
    lastStatus: 'untested',
    lastError: '',
    lastTestedAt: null,
    tags: [],
  }));
  deleteConnectivityServer.mockResolvedValue(true);
  testOpcUaConnection.mockResolvedValue({ ok: true, error: null, elapsedMs: 12 });
  browseOpcUa.mockImplementation(async (_endpoint: string, nodeId?: string | null) => {
    if (!nodeId) {
      return [
        {
          nodeId: 'ns=3;s=WaterTreatmentPlant',
          browseName: 'WaterTreatmentPlant',
          displayName: 'WaterTreatmentPlant',
          browsePath: 'WaterTreatmentPlant',
          nodeClass: 'Object',
          hasChildren: true,
        },
        {
          nodeId: 'ns=3;s=Fast',
          browseName: 'Fast',
          displayName: 'Fast',
          browsePath: 'Fast',
          nodeClass: 'Object',
          hasChildren: true,
        },
      ];
    }
    if (nodeId === 'ns=3;s=WaterTreatmentPlant') {
      return [
        {
          nodeId: 'ns=3;s=RawWater',
          browseName: 'RawWater',
          displayName: 'RawWater',
          browsePath: 'WaterTreatmentPlant/RawWater',
          nodeClass: 'Object',
          hasChildren: true,
        },
      ];
    }
    return [];
  });
  discoverOpcUaVariables.mockImplementation(async (_endpoint: string, nodeId?: string | null) => {
    if (nodeId === 'ns=3;s=WaterTreatmentPlant') {
      return [
        {
          nodeId: 'ns=3;s=WTP_T101_Level',
          browseName: 'Level',
          displayName: 'Level',
          browsePath: 'RawWater/T101/Level',
          nodeClass: 'Variable',
          hasChildren: false,
        },
      ];
    }
    return [];
  });
  readOpcUaNodes.mockResolvedValue([]);
  subscribeOpcUaVariables.mockResolvedValue([
    {
      serverId: 's1',
      nodeId: 'ns=3;s=WTP_T101_Level',
      browsePath: 'RawWater/T101/Level',
      displayName: 'Level',
      mqttTopic: 'RawWater/T101/Level',
      subscribed: true,
    },
  ]);
  updateConnectivityTagTopic.mockResolvedValue({
    serverId: 's1',
    nodeId: 'ns=3;s=WTP_T101_Level',
    browsePath: 'RawWater/T101/Level',
    displayName: 'Level',
    mqttTopic: 'Plant/T101/Level',
    subscribed: true,
  });
  unsubscribeConnectivityTag.mockResolvedValue(true);
  subscribeOpcUaDataChanges.mockReturnValue(() => () => undefined);
});

describe('access', () => {
  it('shows AccessRestricted when connectivity is denied', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    render(<ConnectivityView />);

    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getConnectivityServers).not.toHaveBeenCalled();
  });
});

describe('the OPC UA server table', () => {
  it('shows a GraphQL catalog error without the empty-plant copy', async () => {
    getConnectivityServers.mockRejectedValue(
      new Error('column connectivity_servers.auth_mode does not exist'),
    );
    render(<ConnectivityView />);

    await waitFor(() =>
      expect(
        screen.getByText(/column connectivity_servers.auth_mode does not exist/i),
      ).toBeTruthy(),
    );
    expect(screen.queryByText(/no opc ua servers yet/i)).toBeNull();
  });

  it('shows the empty-plant copy when the catalog has no servers', async () => {
    getConnectivityServers.mockResolvedValue([]);
    render(<ConnectivityView />);

    await waitFor(() => expect(screen.getByText(/no opc ua servers yet/i)).toBeTruthy());
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });

  it('lists an OPC server and offers Browse data', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());
    expect(screen.getByRole('button', { name: /browse data/i })).toBeTruthy();
  });

  it('hides Add Server when the signed-in role cannot mutate connectivity', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    render(<ConnectivityView />);

    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /add server/i })).toBeNull();
  });

  it('opens the Add Server modal and saves the server', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /add server/i }));
    const nameInput = await screen.findByLabelText('Name');
    const endpointInput = await screen.findByLabelText('Endpoint');
    fireEvent.change(nameInput, { target: { value: 'wtp' } });
    fireEvent.change(endpointInput, { target: { value: 'opc.tcp://desktop-h4hdql2:50000/' } });
    expect(screen.getByLabelText('Protocol')).toBeTruthy();
    expect(screen.getByLabelText('Security policy')).toBeTruthy();
    expect(screen.getByText('Anonymous')).toBeTruthy();
    expect(screen.queryByLabelText('Certificate path')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() => expect(saveConnectivityServer).toHaveBeenCalled());
    expect(saveConnectivityServer).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'wtp', endpoint: 'opc.tcp://desktop-h4hdql2:50000/' }),
    );
    await waitFor(() => expect(testOpcUaConnection).toHaveBeenCalledWith('opc.tcp://desktop-h4hdql2:50000/'));
    await waitFor(() => expect(screen.getAllByText('Connected').length).toBeGreaterThan(0));
  });

  it('does not add a server when username is chosen without a password', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /add server/i }));
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'wtp' } });
    fireEvent.change(screen.getByLabelText('Endpoint'), {
      target: { value: 'opc.tcp://host.docker.internal:50000/' },
    });
    fireEvent.click(screen.getByLabelText('Username/Password'));
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'eng' } });
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }));

    expect(screen.getByText('Username and password are required.')).toBeTruthy();
    expect(saveConnectivityServer).not.toHaveBeenCalled();
  });

  it('tests a connection and reports the outcome', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /test/i }));
    await waitFor(() => expect(testOpcUaConnection).toHaveBeenCalledWith('opc.tcp://desktop-h4hdql2:50000/'));
  });

  it('deletes a server after confirming', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /delete/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }));
    await waitFor(() => expect(deleteConnectivityServer).toHaveBeenCalledWith('s1'));
  });

  it('keeps later protocols on the Add dropdown, not as empty page tabs', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    expect(screen.queryByRole('button', { name: /modbus tcp/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^sql$/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /add server/i }));
    const protocol = await screen.findByLabelText('Protocol');
    expect(protocol).toBeTruthy();
    expect(screen.getByRole('option', { name: 'OPC UA' })).toBeTruthy();
    expect(screen.getByRole('option', { name: /Modbus TCP — later/i })).toBeDisabled();
  });
});

async function openDrawerAndSelectWtp() {
  render(<ConnectivityView />);
  await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: /browse data/i }));
  await waitFor(() => expect(browseOpcUa).toHaveBeenCalledWith('opc.tcp://desktop-h4hdql2:50000/'));
  expect(discoverOpcUaVariables).not.toHaveBeenCalled();
  expect(screen.getByText('WaterTreatmentPlant')).toBeTruthy();
  expect(screen.getByText('Fast')).toBeTruthy();
  fireEvent.click(screen.getByText('WaterTreatmentPlant'));
  await waitFor(() =>
    expect(discoverOpcUaVariables).toHaveBeenCalledWith(
      'opc.tcp://desktop-h4hdql2:50000/',
      'ns=3;s=WaterTreatmentPlant',
    ),
  );
}

describe('the Browse data drawer', () => {
  it('browses the address space, then discovers only the selected folder', async () => {
    await openDrawerAndSelectWtp();
    expect(screen.getAllByText('RawWater/T101/Level').length).toBeGreaterThan(0);
    expect(screen.getByText('RawWater')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /subscribe folder/i }));
    await waitFor(() =>
      expect(subscribeOpcUaVariables).toHaveBeenCalledWith('s1', 'ns=3;s=WaterTreatmentPlant'),
    );

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    const topicInput = screen.getByDisplayValue('RawWater/T101/Level');
    fireEvent.change(topicInput, { target: { value: 'Plant/T101/Level' } });
    fireEvent.blur(topicInput);
    await waitFor(() =>
      expect(updateConnectivityTagTopic).toHaveBeenCalledWith('s1', 'ns=3;s=WTP_T101_Level', 'Plant/T101/Level'),
    );
  });

  it('unsubscribes a tag from the drawer', async () => {
    await openDrawerAndSelectWtp();
    fireEvent.click(screen.getByRole('button', { name: /subscribe folder/i }));
    await waitFor(() => expect(subscribeOpcUaVariables).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /unsubscribe/i }));
    await waitFor(() => expect(unsubscribeConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=WTP_T101_Level'));
  });

  it('opens the signal terminal when the server name is clicked', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /open opcplc/i }));
    expect(await screen.findByRole('dialog', { name: /browse opc ua data/i })).toBeTruthy();
    await waitFor(() => expect(browseOpcUa).toHaveBeenCalled());
  });

  it('shows catalog-subscribed signals when the terminal opens, without picking a folder', async () => {
    getConnectivityServers.mockResolvedValue([
      {
        ...SERVER,
        tags: [
          {
            serverId: 's1',
            nodeId: 'ns=3;s=WTP_T101_Level',
            browsePath: 'RawWater/T101/Level',
            displayName: 'Level',
            mqttTopic: 'RawWater/T101/Level',
            subscribed: true,
          },
        ],
      },
    ]);
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /open opcplc/i }));
    expect(await screen.findByText('Level')).toBeTruthy();
    expect(screen.getAllByText('RawWater/T101/Level').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /unsubscribe/i })).toBeTruthy();
    expect(discoverOpcUaVariables).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(readOpcUaNodes).toHaveBeenCalledWith('opc.tcp://desktop-h4hdql2:50000/', [
        'ns=3;s=WTP_T101_Level',
      ]),
    );
  });

  it('uses the same light surfaces for sidebar, title, and live badge', async () => {
    render(<ConnectivityView />);
    await waitFor(() => expect(screen.getByText('opcplc')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /open opcplc/i }));
    const dialog = await screen.findByRole('dialog', { name: /browse opc ua data/i });
    const chrome = within(dialog);

    expect(chrome.getByText('opcplc').className).toContain('text-foreground');
    expect(chrome.getByText('Address space').className).toContain('text-muted-foreground');
    expect(chrome.getByText('Live').closest('div')?.className).toMatch(/bg-muted/);
    expect(dialog.innerHTML).not.toContain('bg-zinc-950');
    expect(dialog.innerHTML).not.toContain('text-white');
  });

  it('keeps subscribed signals after the terminal is closed and opened again', async () => {
    await openDrawerAndSelectWtp();
    fireEvent.click(screen.getByRole('button', { name: /subscribe folder/i }));
    await waitFor(() => expect(subscribeOpcUaVariables).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /browse opc ua data/i })).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: /open opcplc/i }));
    expect(await screen.findByText('Level')).toBeTruthy();
    expect(screen.getByRole('button', { name: /unsubscribe/i })).toBeTruthy();
  });
});
