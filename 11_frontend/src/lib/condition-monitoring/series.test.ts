import { describe, expect, it } from 'vitest';
import {
  booleanTransitions,
  downsample,
  extractSample,
  isBooleanPayload,
  mergeSeries,
  numericTableRows,
} from './series';

describe('extractSample', () => {
  it('reads collector { value } and a bare number', () => {
    const a = extractSample({ value: 1.35 }, '2026-09-05T17:20:00.000Z');
    expect(a?.v).toBe(1.35);
    expect(a?.boolean).toBe(false);
    const b = extractSample(42, '2026-09-05T17:20:00.000Z');
    expect(b?.v).toBe(42);
  });

  it('stores booleans as 0/1 and reads quality when present', () => {
    const s = extractSample({ value: true, quality: 'GOOD' }, '2026-09-05T17:20:00.000Z');
    expect(s?.v).toBe(1);
    expect(s?.boolean).toBe(true);
    expect(s?.quality).toBe('GOOD');
  });

  it('returns null when there is no numeric or boolean value', () => {
    expect(extractSample({ unit: 'bar' }, '2026-09-05T17:20:00.000Z')).toBeNull();
  });
});

describe('isBooleanPayload', () => {
  it('detects boolean value or type BOOLEAN', () => {
    expect(isBooleanPayload(true)).toBe(true);
    expect(isBooleanPayload({ value: false })).toBe(true);
    expect(isBooleanPayload({ value: 1, type: 'BOOLEAN' })).toBe(true);
    expect(isBooleanPayload({ value: 1.35 })).toBe(false);
  });
});

describe('mergeSeries', () => {
  it('appends live after historian and drops points outside the window', () => {
    const from = Date.parse('2026-09-05T17:00:00.000Z');
    const to = Date.parse('2026-09-05T18:00:00.000Z');
    const historian = [
      extractSample(1, '2026-09-05T16:59:00.000Z')!,
      extractSample(2, '2026-09-05T17:10:00.000Z')!,
    ];
    const live = [extractSample(3, '2026-09-05T17:50:00.000Z')!];
    const merged = mergeSeries(historian, live, from, to);
    expect(merged.map((s) => s.v)).toEqual([2, 3]);
  });
});

describe('numericTableRows', () => {
  it('returns newest first and caps at 200', () => {
    const samples = Array.from({ length: 210 }, (_, i) =>
      extractSample(i, new Date(Date.parse('2026-09-05T17:00:00.000Z') + i * 1000).toISOString())!,
    );
    const rows = numericTableRows(samples);
    expect(rows).toHaveLength(200);
    expect(rows[0].v).toBe(209);
  });
});

describe('booleanTransitions', () => {
  it('lists 0→1 and 1→0 only', () => {
    const samples = [
      extractSample({ value: false }, '2026-09-05T17:00:00.000Z')!,
      extractSample({ value: false }, '2026-09-05T17:01:00.000Z')!,
      extractSample({ value: true }, '2026-09-05T17:02:00.000Z')!,
      extractSample({ value: true }, '2026-09-05T17:03:00.000Z')!,
      extractSample({ value: false }, '2026-09-05T17:04:00.000Z')!,
    ];
    const rows = booleanTransitions(samples);
    expect(rows).toEqual([
      { t: Date.parse('2026-09-05T17:04:00.000Z'), from: 1, to: 0 },
      { t: Date.parse('2026-09-05T17:02:00.000Z'), from: 0, to: 1 },
    ]);
  });
});

describe('downsample', () => {
  it('does not change series at or under 1500 points', () => {
    const samples = Array.from({ length: 10 }, (_, i) =>
      extractSample(i, new Date(1_000_000 + i * 1000).toISOString())!,
    );
    expect(downsample(samples)).toHaveLength(10);
  });

  it('caps a long series at 1500 using min/max buckets', () => {
    const samples = Array.from({ length: 4000 }, (_, i) =>
      extractSample(i, new Date(1_000_000 + i * 1000).toISOString())!,
    );
    expect(downsample(samples).length).toBeLessThanOrEqual(1500);
    expect(downsample(samples).length).toBeGreaterThan(2);
  });
});
