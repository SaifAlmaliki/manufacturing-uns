import { describe, expect, it } from 'vitest';
import { DEFAULT_TIME_RANGE, rangeWindow } from './time-range';

describe('rangeWindow', () => {
  it('defaults to 60 minutes and computes 15m / 4h / 24h from nowMs', () => {
    expect(DEFAULT_TIME_RANGE).toBe('60m');
    const now = Date.parse('2026-09-05T18:00:00.000Z');
    expect(rangeWindow('60m', now).fromIso).toBe('2026-09-05T17:00:00.000Z');
    expect(rangeWindow('15m', now).fromIso).toBe('2026-09-05T17:45:00.000Z');
    expect(rangeWindow('4h', now).fromIso).toBe('2026-09-05T14:00:00.000Z');
    expect(rangeWindow('24h', now).fromIso).toBe('2026-09-04T18:00:00.000Z');
    expect(rangeWindow('60m', now).toIso).toBe('2026-09-05T18:00:00.000Z');
  });
});
