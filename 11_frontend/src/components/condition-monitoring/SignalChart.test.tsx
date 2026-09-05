import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { chartPath, formatChartTime, SignalChart } from './SignalChart';
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

  it('scales X from fromMs/toMs when provided, not sample min/max', () => {
    const samples = [s(50, 0), s(100, 10)];
    const dWindowed = chartPath(samples, 100, 40, 'line', 0, 100);
    const dSample = chartPath(samples, 100, 40, 'line');
    expect(dWindowed).not.toBe(dSample);
    // PAD=4, drawable width=92: t=50 of [0,100] → x=50; sample-extent t=50 is the left pad.
    expect(dWindowed.startsWith('M50.0,')).toBe(true);
    expect(dSample.startsWith('M4.0,')).toBe(true);
  });
});

describe('SignalChart', () => {
  it('shows the empty historian copy when there are no samples', () => {
    render(<SignalChart samples={[]} mode="line" />);
    expect(screen.getByText(/no historian points in range/i)).toBeTruthy();
  });

  it('exposes time and value on an accessible hover target', () => {
    render(<SignalChart samples={[s(Date.parse('2026-09-05T17:02:00.000Z'), 1.35)]} mode="line" />);
    expect(screen.getByLabelText(/1\.35/)).toBeTruthy();
  });

  it('labels the time window and value range on the axes', () => {
    const from = Date.parse('2026-09-05T17:00:00.000Z');
    const to = Date.parse('2026-09-05T17:15:00.000Z');
    render(
      <SignalChart samples={[s(from, 1.1), s(to, 2.4)]} mode="line" fromMs={from} toMs={to} />,
    );
    expect(screen.getByTestId('chart-x-start')).toHaveTextContent(formatChartTime(from));
    expect(screen.getByTestId('chart-x-end')).toHaveTextContent(formatChartTime(to));
    expect(screen.getByTestId('chart-y-min')).toHaveTextContent('1.1');
    expect(screen.getByTestId('chart-y-max')).toHaveTextContent('2.4');
  });

  it('shows a live hover readout with time and value', () => {
    const t = Date.parse('2026-09-05T17:02:00.000Z');
    render(<SignalChart samples={[s(t, 1.35)]} mode="line" />);
    const svg = screen.getByRole('img', { name: /signal trend/i });
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      bottom: 132,
      right: 320,
      width: 320,
      height: 132,
      toJSON: () => ({}),
    });
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.mouseMove(svg, { clientX: 40, clientY: 40 });
    const readout = screen.getByRole('status');
    expect(readout.textContent).toMatch(/1\.35/);
    expect(readout.textContent).toContain(formatChartTime(t));
  });
});
