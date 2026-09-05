export const TIME_RANGE_PRESETS = ['15m', '60m', '4h', '24h'] as const;
export type TimeRangePreset = (typeof TIME_RANGE_PRESETS)[number];
export const DEFAULT_TIME_RANGE: TimeRangePreset = '60m';

const MS: Record<TimeRangePreset, number> = {
  '15m': 15 * 60 * 1000,
  '60m': 60 * 60 * 1000,
  '4h': 4 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
};

export function rangeWindow(
  preset: TimeRangePreset,
  nowMs: number,
): { fromIso: string; toIso: string; fromMs: number; toMs: number } {
  const fromMs = nowMs - MS[preset];
  return {
    fromMs,
    toMs: nowMs,
    fromIso: new Date(fromMs).toISOString(),
    toIso: new Date(nowMs).toISOString(),
  };
}
