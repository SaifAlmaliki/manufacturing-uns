import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SignalCard } from './SignalCard';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import type { Sample } from '../../lib/condition-monitoring/series';

const TAG: GraphqlConnectivityTag = {
  serverId: 's1',
  nodeId: 'n1',
  browsePath: 'P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/P201/Fault',
  subscribed: true,
};

const samples: Sample[] = [
  { t: Date.parse('2026-09-05T17:00:00.000Z'), v: 0, quality: null, boolean: true },
  { t: Date.parse('2026-09-05T17:02:00.000Z'), v: 1, quality: 'GOOD', boolean: true },
];

describe('SignalCard', () => {
  it('shows name, topic, latest value, and Graph by default', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    expect(screen.getByText('Fault')).toBeTruthy();
    expect(screen.getByText('Server/OpcPlc/P201/Fault')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByRole('img', { name: /signal trend/i })).toBeTruthy();
    expect(screen.queryByText(/0 → 1/)).toBeNull();
  });

  it('switches to a boolean transition table', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    fireEvent.click(screen.getByRole('button', { name: /^table$/i }));
    expect(screen.getByText(/0 → 1/)).toBeTruthy();
    expect(screen.queryByRole('img', { name: /signal trend/i })).toBeNull();
  });

  it('renders — when quality is missing', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={{ ...samples[1], quality: null }} />);
    expect(screen.getByText('—')).toBeTruthy();
  });
});
