export type Sample = {
  t: number;
  v: number;
  quality: string | null;
  boolean: boolean;
};

function asBooleanFlag(payload: unknown): boolean {
  if (typeof payload === 'boolean') return true;
  if (payload && typeof payload === 'object') {
    const rec = payload as Record<string, unknown>;
    if (typeof rec.value === 'boolean') return true;
    const type = String(rec.type ?? rec.Type ?? '').toUpperCase();
    if (type === 'BOOLEAN') return true;
  }
  return false;
}

export function isBooleanPayload(payload: unknown): boolean {
  return asBooleanFlag(payload);
}

function rawValue(payload: unknown): unknown {
  if (payload && typeof payload === 'object' && 'value' in payload) {
    return (payload as { value: unknown }).value;
  }
  return payload;
}

export function extractSample(payload: unknown, timestamp: string): Sample | null {
  const raw = rawValue(payload);
  const boolean = asBooleanFlag(payload) || typeof raw === 'boolean';
  let v: number | null = null;
  if (typeof raw === 'boolean') v = raw ? 1 : 0;
  else if (typeof raw === 'number' && Number.isFinite(raw)) v = raw;
  else if (raw === 'true' || raw === 'false') v = raw === 'true' ? 1 : 0;
  if (v === null) return null;
  const rec = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const qualityRaw = rec.quality ?? rec.Quality;
  const quality = typeof qualityRaw === 'string' && qualityRaw.trim() ? qualityRaw : null;
  const t = Date.parse(timestamp);
  if (!Number.isFinite(t)) return null;
  return { t, v, quality, boolean };
}

export function mergeSeries(
  historian: Sample[],
  live: Sample[],
  fromMs: number,
  toMs: number,
): Sample[] {
  const inWindow = (s: Sample) => s.t >= fromMs && s.t <= toMs;
  const merged = [...historian.filter(inWindow), ...live.filter(inWindow)];
  merged.sort((a, b) => a.t - b.t);
  return merged;
}

export function numericTableRows(samples: Sample[], cap = 200): Sample[] {
  return [...samples].sort((a, b) => b.t - a.t).slice(0, cap);
}

export function booleanTransitions(
  samples: Sample[],
  cap = 200,
): { t: number; from: number; to: number }[] {
  const ordered = [...samples].sort((a, b) => a.t - b.t);
  const rows: { t: number; from: number; to: number }[] = [];
  for (let i = 1; i < ordered.length; i += 1) {
    const from = ordered[i - 1].v ? 1 : 0;
    const to = ordered[i].v ? 1 : 0;
    if (from !== to) rows.push({ t: ordered[i].t, from, to });
  }
  return rows.reverse().slice(0, cap);
}

export function downsample(samples: Sample[], maxPoints = 1500): Sample[] {
  if (samples.length <= maxPoints) return samples;
  const bucketCount = Math.floor(maxPoints / 2);
  const ordered = [...samples].sort((a, b) => a.t - b.t);
  const start = ordered[0].t;
  const span = Math.max(1, ordered[ordered.length - 1].t - start);
  const buckets: Sample[][] = Array.from({ length: bucketCount }, () => []);
  for (const s of ordered) {
    const index = Math.min(bucketCount - 1, Math.floor(((s.t - start) / span) * bucketCount));
    buckets[index].push(s);
  }
  const out: Sample[] = [];
  for (const bucket of buckets) {
    if (bucket.length === 0) continue;
    const min = bucket.reduce((a, b) => (a.v <= b.v ? a : b));
    const max = bucket.reduce((a, b) => (a.v >= b.v ? a : b));
    if (min.t <= max.t) out.push(min, max);
    else out.push(max, min);
  }
  return out.slice(0, maxPoints);
}
