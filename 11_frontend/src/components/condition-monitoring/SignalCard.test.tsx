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
  it('shows name, topic, latest value, BOOLEAN hint, and Graph by default', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    expect(screen.getByText('Fault')).toBeTruthy();
    expect(screen.getByText('Server/OpcPlc/P201/Fault')).toBeTruthy();
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(screen.getByText('BOOLEAN')).toBeTruthy();
    expect(screen.getByRole('img', { name: /signal trend/i })).toBeTruthy();
    expect(screen.queryByText(/0 → 1/)).toBeNull();
  });

  it('shows DOUBLE next to a numeric latest value', () => {
    const numeric: Sample[] = [{ t: Date.parse('2026-09-05T17:00:00.000Z'), v: 1.35, quality: 'GOOD', boolean: false }];
    render(
      <SignalCard tag={{ ...TAG, displayName: 'Speed', mqttTopic: 'Server/OpcPlc/P202/Speed' }} samples={numeric} latest={numeric[0]} />,
    );
    expect(screen.getAllByText('1.35').length).toBeGreaterThan(0);
    expect(screen.getByText('DOUBLE')).toBeTruthy();
    expect(screen.queryByText('BOOLEAN')).toBeNull();
  });

  it('switches to a boolean transition table', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    fireEvent.click(screen.getByRole('button', { name: /^table$/i }));
    expect(screen.getByText(/0 → 1/)).toBeTruthy();
    expect(screen.queryByRole('img', { name: /signal trend/i })).toBeNull();
  });

  it('keeps the table inside a fixed-height scroll region', () => {
    const numeric: Sample[] = Array.from({ length: 40 }, (_, i) => ({
      t: Date.parse('2026-09-05T17:00:00.000Z') + i * 1000,
      v: 1 + i / 100,
      quality: 'GOOD',
      boolean: false,
    }));
    render(
      <SignalCard
        tag={{ ...TAG, displayName: 'Speed', mqttTopic: 'Server/OpcPlc/P202/Speed' }}
        samples={numeric}
        latest={numeric[numeric.length - 1]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^table$/i }));
    const body = screen.getByTestId('signal-card-body');
    const card = body.parentElement;
    expect(card?.className).toMatch(/h-\[17rem\]/);
    expect(card?.className).toMatch(/overflow-hidden/);
    expect(body.className).toMatch(/overflow-y-auto/);
    expect(screen.getByText('1.01')).toBeTruthy();
  });

  it('renders — when quality is missing', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={{ ...samples[1], quality: null }} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('shows unit of measure and asset name next to the value', () => {
    render(
      <SignalCard
        tag={{ ...TAG, unitOfMeasure: '°C', assetDisplayName: 'Furnace', dataType: 'Double' }}
        samples={[{ t: 1, v: 1234, quality: 'GOOD', boolean: false }]}
        latest={{ t: 1, v: 1234, quality: 'GOOD', boolean: false }}
      />,
    );
    expect(screen.getAllByText(/1234/).length).toBeGreaterThan(0);
    expect(screen.getByText('°C')).toBeTruthy();
    expect(screen.getByText('Furnace')).toBeTruthy();
  });
});
