import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import type { AlertRule } from '../../types/alarm';

const getSubscribedSignals = vi.hoisted(() => vi.fn());
const createRule = vi.hoisted(() => vi.fn());
const updateRule = vi.hoisted(() => vi.fn());
const alarms = vi.hoisted(() => ({
  createRule,
  updateRule,
  canPersistRules: true,
  rulesError: null as string | null,
}));

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getSubscribedSignals },
}));
vi.mock('../../context/AlarmContext', () => ({ useAlarms: () => alarms }));

import { AlertRuleEditorModal } from './AlertRuleEditorModal';

const TEMP: GraphqlSubscribedSignal = {
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Temperature',
  displayName: 'Temperature',
  mqttTopic: 'Plant/Reactor01/Temperature',
  subscribed: true,
  unitOfMeasure: '°C',
  dataType: 'Double',
  assetDisplayName: 'Reactor 01',
  labels: [],
};

const FLOW: GraphqlSubscribedSignal = {
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=F201',
  browsePath: 'F201/Flow',
  displayName: 'Flow',
  mqttTopic: 'Plant/Line/Flow',
  subscribed: true,
  unitOfMeasure: 'm³/h',
  dataType: 'Double',
  labels: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  alarms.canPersistRules = true;
  alarms.rulesError = null;
  getSubscribedSignals.mockResolvedValue([TEMP, FLOW]);
  createRule.mockResolvedValue({ id: 'r1' });
  updateRule.mockResolvedValue(undefined);
});

describe('AlertRuleEditorModal', () => {
  it('opens on the Signal tab and lists subscribed signals', async () => {
    render(<AlertRuleEditorModal rule={null} onClose={() => undefined} />);

    expect(screen.getByRole('heading', { name: 'New alert rule' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Signal' })).toBeTruthy();
    expect(screen.queryByLabelText(/rule name/i)).toBeNull();

    await waitFor(() => expect(screen.getByText('Temperature')).toBeTruthy());
    expect(screen.getByText('Plant/Reactor01/Temperature')).toBeTruthy();
    expect(screen.getByText('Flow')).toBeTruthy();
  });

  it('fills the rule from the selected signal before the condition is chosen', async () => {
    render(<AlertRuleEditorModal rule={null} onClose={() => undefined} />);
    await waitFor(() => expect(screen.getByText('Temperature')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /temperature/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(screen.getByLabelText(/rule name/i)).toHaveValue('Reactor 01 Temperature');
    expect(screen.getByText('Plant/Reactor01/Temperature')).toBeTruthy();
    expect(screen.getByLabelText(/condition/i)).toHaveValue('GREATER_THAN');
  });

  it('filters the catalog and requires a signal before create', async () => {
    render(<AlertRuleEditorModal rule={null} onClose={() => undefined} />);
    await waitFor(() => expect(screen.getByText('Temperature')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Search signals'), { target: { value: 'flow' } });
    expect(screen.queryByText('Temperature')).toBeNull();
    expect(screen.getByText('Flow')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Create rule' }));
    expect(screen.getByText('Select a signal first.')).toBeTruthy();
    expect(createRule).not.toHaveBeenCalled();
  });

  it('preselects the subscribed signal when editing a rule', async () => {
    const rule = {
      id: 'r1',
      name: 'Existing high',
      description: '',
      enabled: true,
      severity: 'HIGH',
      category: 'TEMPERATURE',
      topic: 'Plant/Reactor01/Temperature',
      metricField: 'value',
      condition: 'GREATER_THAN',
      thresholdValue: 85,
      unit: '°C',
      delaySeconds: 0,
      targetRoles: ['operator'],
      autoResolveOnNormal: true,
      actions: {
        inAppNotification: true,
        audioChime: true,
        mqttPublishOnTrigger: false,
        emailWebhook: false,
      },
      triggerCount: 0,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    } as AlertRule;

    render(<AlertRuleEditorModal rule={rule} onClose={() => undefined} />);
    await waitFor(() => expect(screen.getByText('Temperature')).toBeTruthy());

    expect(screen.getByRole('button', { name: /temperature/i })).toHaveAttribute('aria-pressed', 'true');
  });
});
