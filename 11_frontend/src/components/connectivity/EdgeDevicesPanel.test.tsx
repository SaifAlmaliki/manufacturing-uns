import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getEdgeDevices = vi.hoisted(() => vi.fn());
const registerEdgeDevice = vi.hoisted(() => vi.fn());
const createEdgeEnrollmentToken = vi.hoisted(() => vi.fn());
const grantEdgeAccess = vi.hoisted(() => vi.fn());

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getEdgeDevices,
    registerEdgeDevice,
    createEdgeEnrollmentToken,
    grantEdgeAccess,
  },
}));

import { EdgeDevicesPanel } from './EdgeDevicesPanel';

const EDGE = {
  edgeId: 'edge-sim-01',
  displayName: 'Halabja WTP simulation edge',
  status: 'active',
  desiredRevision: 4,
  appliedRevision: 3,
  appliedPhase: 'applying',
  lastSeen: '2026-09-12T12:00:00.000Z',
  capabilities: { protocols: ['opc_ua', 'modbus'] },
};

beforeEach(() => {
  vi.clearAllMocks();
  createEdgeEnrollmentToken.mockResolvedValue('enroll-token-abc');
  grantEdgeAccess.mockResolvedValue(true);
  registerEdgeDevice.mockResolvedValue(EDGE);
});

describe('EdgeDevicesPanel', () => {
  it('shows reconciliation KPIs for the selected edge', () => {
    render(
      <EdgeDevicesPanel
        edges={[EDGE]}
        selectedEdgeId="edge-sim-01"
        onSelectEdge={vi.fn()}
        onEdgesChange={vi.fn()}
        isAdmin={true}
        simulationHint="Simulation fixtures — not a live PLC or vendor connection."
      />,
    );

    expect(screen.getAllByText('Halabja WTP simulation edge').length).toBeGreaterThan(0);
    expect(screen.getByText('Applying')).toBeTruthy();
    expect(screen.getByText('1 revision behind')).toBeTruthy();
    expect(screen.getByText(/simulation fixtures/i)).toBeTruthy();
  });

  it('reveals a one-time enrollment token without persisting it', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    render(
      <EdgeDevicesPanel
        edges={[EDGE]}
        selectedEdgeId="edge-sim-01"
        onSelectEdge={vi.fn()}
        onEdgesChange={vi.fn()}
        isAdmin={true}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /enroll/i }));
    await waitFor(() => expect(createEdgeEnrollmentToken).toHaveBeenCalledWith('edge-sim-01'));
    expect(screen.getByText('enroll-token-abc')).toBeTruthy();
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });

  it('grants engineer write access to an edge', async () => {
    render(
      <EdgeDevicesPanel
        edges={[EDGE]}
        selectedEdgeId="edge-sim-01"
        onSelectEdge={vi.fn()}
        onEdgesChange={vi.fn()}
        isAdmin={true}
      />,
    );

    fireEvent.change(screen.getByLabelText('Engineer user id'), {
      target: { value: 'engineer-42' },
    });
    fireEvent.click(screen.getByRole('button', { name: /grant write access/i }));
    await waitFor(() =>
      expect(grantEdgeAccess).toHaveBeenCalledWith('edge-sim-01', 'engineer-42'),
    );
  });

  it('registers a new edge device', async () => {
    const onEdgesChange = vi.fn();
    const onSelectEdge = vi.fn();
    render(
      <EdgeDevicesPanel
        edges={[]}
        selectedEdgeId={null}
        onSelectEdge={onSelectEdge}
        onEdgesChange={onEdgesChange}
        isAdmin={true}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /register edge/i }));
    fireEvent.change(screen.getByLabelText('Edge ID'), { target: { value: 'edge-sim-01' } });
    fireEvent.change(screen.getByLabelText('Display name'), {
      target: { value: 'Halabja WTP simulation edge' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^register$/i }));

    await waitFor(() => expect(registerEdgeDevice).toHaveBeenCalled());
    expect(onEdgesChange).toHaveBeenCalled();
    expect(onSelectEdge).toHaveBeenCalledWith('edge-sim-01');
  });
});
