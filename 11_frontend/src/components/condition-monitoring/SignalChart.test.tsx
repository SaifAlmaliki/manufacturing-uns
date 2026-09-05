import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { chartPath, SignalChart } from './SignalChart';
import type { Sample } from '../../lib/condition-monitoring/series';

const s = (t: number, v: number): Sample => ({ t, v, quality: null, boolean: false });

describe('chartPath', () => {
  it('draws a continuous polyline for line mode', () => {
    const d = chartPath([s(0, 0), s(10, 10)], 100, 40, 'line');
    expect(d.startsWith('M')).toBe(true);
    expect(d.includes('H')).toBe(false);
  });

  it('holds the last Y then steps for boolean mode', () => {
    const d = chartPath([s(0, 0), s(10, 1)], 100, 40, 'step');
    expect(d.includes('H') || /L[\d.]+,[\d.]+ L/.test(d)).toBe(true);
  });
});

describe('SignalChart', () => {
  it('shows the empty historian copy when there are no samples', () => {
    render(<SignalChart samples={[]} mode="line" />);
    expect(screen.getByText(/no historian points in range/i)).toBeTruthy();
  });
});
