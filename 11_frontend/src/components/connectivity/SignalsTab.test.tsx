import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getSubscribedSignals = vi.hoisted(() => vi.fn());
const unitsOfMeasure = vi.hoisted(() => vi.fn());
const signalLabels = vi.hoisted(() => vi.fn());
const getAssets = vi.hoisted(() => vi.fn());
const updateConnectivityTag = vi.hoisted(() => vi.fn());
const saveUnitOfMeasure = vi.hoisted(() => vi.fn());
const unsubscribeConnectivityTag = vi.hoisted(() => vi.fn());
const saveSignalLabel = vi.hoisted(() => vi.fn());
const getConnectivityServers = vi.hoisted(() => vi.fn());
const readOpcUaNodes = vi.hoisted(() => vi.fn());
const subscribeOpcUaDataChanges = vi.hoisted(() => vi.fn());

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getSubscribedSignals,
    unitsOfMeasure,
    signalLabels,
    getAssets,
    updateConnectivityTag,
    saveUnitOfMeasure,
    unsubscribeConnectivityTag,
    saveSignalLabel,
    getConnectivityServers,
    readOpcUaNodes,
    subscribeOpcUaDataChanges,
  },
}));

import { SignalsTab } from './SignalsTab';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';

const SIGNAL: GraphqlSubscribedSignal = {
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Level',
  displayName: 'Level',
  mqttTopic: 'Plant/T101/Level',
  subscribed: true,
  unitOfMeasure: null,
  labels: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  getSubscribedSignals.mockResolvedValue([SIGNAL]);
  unitsOfMeasure.mockResolvedValue([{ symbol: '°C', name: 'Celsius' }]);
  signalLabels.mockResolvedValue(['Cycle']);
  getAssets.mockResolvedValue([
    { id: 9, path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA' },
  ]);
  updateConnectivityTag.mockImplementation(async (_serverId, _nodeId, patch) => ({
    ...SIGNAL,
    ...patch,
  }));
  saveUnitOfMeasure.mockResolvedValue({ symbol: 'NTU', name: null });
  unsubscribeConnectivityTag.mockResolvedValue(true);
  saveSignalLabel.mockResolvedValue('Custom');
  getConnectivityServers.mockResolvedValue([
    {
      id: 's1',
      name: 'opcplc',
      protocol: 'opc_ua',
      endpoint: 'opc.tcp://host.docker.internal:50000/',
      lastStatus: 'connected',
      lastError: '',
      tags: [],
    },
  ]);
  readOpcUaNodes.mockResolvedValue([]);
  subscribeOpcUaDataChanges.mockReturnValue(() => undefined);
});

describe('SignalsTab', () => {
  it('lists a subscribed signal and saves a unit from the dropdown', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());
    expect(screen.getAllByText('opcplc').length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText('Unit of Measure for Level'), { target: { value: '°C' } });
    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', {
        unitOfMeasure: '°C',
      }),
    );
  });

  it('persists Other unit and then it appears in the dropdown', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByLabelText('Unit of Measure for Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Unit of Measure for Level'), {
      target: { value: '__other__' },
    });
    fireEvent.change(screen.getByLabelText('New Unit of Measure'), { target: { value: 'NTU' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(saveUnitOfMeasure).toHaveBeenCalledWith('NTU', undefined));
    await waitFor(() => expect(screen.getByRole('option', { name: 'NTU' })).toBeTruthy());
  });

  it('shows empty copy when nothing is subscribed', async () => {
    getSubscribedSignals.mockResolvedValue([]);
    render(<SignalsTab />);
    await waitFor(() =>
      expect(
        screen.getByText(
          'Subscribe variables from Browse data on a server — then attach units here.',
        ),
      ).toBeTruthy(),
    );
  });

  it('shows a rose load-error banner instead of empty copy', async () => {
    getSubscribedSignals.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText(/GraphQL endpoint unreachable/i)).toBeTruthy());
    expect(
      screen.queryByText(
        'Subscribe variables from Browse data on a server — then attach units here.',
      ),
    ).toBeNull();
  });

  it('shows a rose load-error banner when a catalog call fails but still renders the table', async () => {
    unitsOfMeasure.mockRejectedValue(new Error('units catalog unreachable'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText(/units catalog unreachable/i)).toBeTruthy());
    expect(screen.getByText('Level')).toBeTruthy();
  });

  it('opens the context panel and saves name and topic', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Level' }));
    const dialog = await screen.findByRole('dialog');
    const panel = within(dialog);

    fireEvent.change(panel.getByLabelText('Name'), { target: { value: 'Tank Level' } });
    fireEvent.change(panel.getByLabelText('Topic'), { target: { value: 'Plant/T101/TankLevel' } });
    fireEvent.click(panel.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', {
        displayName: 'Tank Level',
        mqttTopic: 'Plant/T101/TankLevel',
      }),
    );
  });

  it('unsubscribes from the panel after confirm', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Level' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /^unsubscribe$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() =>
      expect(unsubscribeConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101'),
    );
    await waitFor(() => expect(screen.queryByText('Level')).toBeNull());
  });

  it('bulk-applies a Unit of Measure without sending mqttTopic', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.click(screen.getByRole('checkbox', { name: /select level/i }));
    fireEvent.change(screen.getByLabelText('Apply Unit of Measure'), { target: { value: '°C' } });

    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', {
        unitOfMeasure: '°C',
      }),
    );
    expect(updateConnectivityTag.mock.calls[0][2]).not.toHaveProperty('mqttTopic');
  });

  it('assigns an Asset without rewriting mqttTopic', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Asset for Level'), { target: { value: '9' } });
    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', { assetId: 9 }),
    );
    expect(updateConnectivityTag.mock.calls[0][2]).not.toHaveProperty('mqttTopic');
  });

  it('shows a rose banner when a table save fails', async () => {
    updateConnectivityTag.mockRejectedValue(new Error('tag update failed'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Unit of Measure for Level'), { target: { value: '°C' } });
    await waitFor(() => expect(screen.getByText(/tag update failed/i)).toBeTruthy());
  });

  it('keeps the Other field when saveUnitOfMeasure fails', async () => {
    saveUnitOfMeasure.mockRejectedValue(new Error('unit catalog failed'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByLabelText('Unit of Measure for Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Unit of Measure for Level'), {
      target: { value: '__other__' },
    });
    fireEvent.change(screen.getByLabelText('New Unit of Measure'), { target: { value: 'NTU' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/unit catalog failed/i)).toBeTruthy());
    expect((screen.getByLabelText('New Unit of Measure') as HTMLInputElement).value).toBe('NTU');
  });

  it('shows a rose banner when bulk apply fails', async () => {
    updateConnectivityTag.mockRejectedValue(new Error('bulk patch failed'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.click(screen.getByRole('checkbox', { name: /select level/i }));
    fireEvent.change(screen.getByLabelText('Apply Unit of Measure'), { target: { value: '°C' } });

    await waitFor(() => expect(screen.getByText(/bulk patch failed/i)).toBeTruthy());
  });

  it('persists Other label on a row and then it appears as a chip', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByLabelText('Add label to Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Add label to Level'), {
      target: { value: '__other__' },
    });
    fireEvent.change(screen.getByLabelText('New signal label'), { target: { value: 'Custom' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(saveSignalLabel).toHaveBeenCalledWith('Custom'));
    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', {
        labels: ['Custom'],
      }),
    );
    await waitFor(() => expect(screen.getAllByText('Custom').length).toBeGreaterThan(0));
  });

  it('bulk-applies Other label via saveSignalLabel', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    fireEvent.click(screen.getByRole('checkbox', { name: /select level/i }));
    fireEvent.change(screen.getByLabelText('Apply label'), { target: { value: '__other__' } });
    fireEvent.change(screen.getByLabelText('New signal label'), { target: { value: 'Custom' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(saveSignalLabel).toHaveBeenCalledWith('Custom'));
    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', {
        labels: ['Custom'],
      }),
    );
  });

  it('shows assigned Asset, Unit of Measure, class, and data type on the row', async () => {
    getSubscribedSignals.mockResolvedValue([
      {
        ...SIGNAL,
        assetId: 9,
        unitOfMeasure: '°C',
        semanticClass: 'MeasuredValue',
        dataType: 'Double',
      },
    ]);
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    expect((screen.getByLabelText('Asset for Level') as HTMLSelectElement).value).toBe('9');
    expect((screen.getByLabelText('Unit of Measure for Level') as HTMLSelectElement).value).toBe(
      '°C',
    );
    expect((screen.getByLabelText('Class for Level') as HTMLSelectElement).value).toBe(
      'MeasuredValue',
    );
    expect((screen.getByLabelText('Data type for Level') as HTMLSelectElement).value).toBe(
      'Double',
    );
    expect(screen.getByRole('option', { name: '°C', selected: true })).toBeTruthy();
  });

  it('keeps an assigned Unit of Measure visible when it is missing from the catalog', async () => {
    getSubscribedSignals.mockResolvedValue([{ ...SIGNAL, unitOfMeasure: 'NTU' }]);
    unitsOfMeasure.mockResolvedValue([{ symbol: '°C', name: 'Celsius' }]);
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByLabelText('Unit of Measure for Level')).toBeTruthy());

    expect((screen.getByLabelText('Unit of Measure for Level') as HTMLSelectElement).value).toBe(
      'NTU',
    );
    expect(screen.getByRole('option', { name: 'NTU' })).toBeTruthy();
  });

  it('shows the MQTT topic and an edit control beside the name', async () => {
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('Level')).toBeTruthy());

    expect(screen.getByText('Plant/T101/Level')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /edit level/i }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
  });

  it('shows the live OPC UA value and health lamp', async () => {
    readOpcUaNodes.mockResolvedValue([
      {
        nodeId: 'ns=3;s=T101',
        displayName: 'Level',
        browsePath: 'T101/Level',
        value: 12.5,
        dataType: 'Double',
        sourceTimestamp: '2026-09-06T18:00:00.000Z',
        serverTimestamp: null,
        status: 'Good',
      },
    ]);
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByText('12.5')).toBeTruthy());
    expect(screen.getByText('Good')).toBeTruthy();
    expect(readOpcUaNodes).toHaveBeenCalledWith('opc.tcp://host.docker.internal:50000/', [
      'ns=3;s=T101',
    ]);
  });

  it('keeps the Other label field when saveSignalLabel fails', async () => {
    saveSignalLabel.mockRejectedValue(new Error('label catalog failed'));
    render(<SignalsTab />);
    await waitFor(() => expect(screen.getByLabelText('Add label to Level')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Add label to Level'), {
      target: { value: '__other__' },
    });
    fireEvent.change(screen.getByLabelText('New signal label'), { target: { value: 'Custom' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/label catalog failed/i)).toBeTruthy());
    expect((screen.getByLabelText('New signal label') as HTMLInputElement).value).toBe('Custom');
  });
});
