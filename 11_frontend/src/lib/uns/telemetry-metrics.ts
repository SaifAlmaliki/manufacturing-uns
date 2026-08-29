/** Helpers for historian charts — exclude epoch/metadata numbers from Y-axis trends. */

const EXCLUDED_CHART_KEYS = new Set([
  'timestamp',
  'last_maintenance',
  'created',
  'modified',
  'seq',
  'sequence',
  'sequenceNumber',
])

const PREFERRED_METRIC_ORDER = [
  'value',
  'operating_hours',
  'performance',
  'Temperature',
  'Pressure',
  'FlowRate',
  'Level',
  'Humidity',
]

export function parseMetricNumber(raw: unknown): number | undefined {
  if (typeof raw === 'boolean' || raw === null || raw === undefined) return undefined
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function looksLikeEpoch(key: string, value: number): boolean {
  const lower = key.toLowerCase()
  if (lower.includes('timestamp') || lower.includes('maintenance') || lower.includes('datetime')) {
    return true
  }
  // Unix epoch seconds (~1e9) or milliseconds (~1e12)
  if (value >= 1_000_000_000) return true
  return false
}

export function isChartableMetric(key: string, raw: unknown): boolean {
  if (EXCLUDED_CHART_KEYS.has(key)) return false
  const value = parseMetricNumber(raw)
  if (value === undefined) return false
  if (looksLikeEpoch(key, value)) return false
  return true
}

export function extractChartableMetrics(payload: unknown): string[] {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    return []
  }
  return Object.entries(payload as Record<string, unknown>)
    .filter(([key, raw]) => isChartableMetric(key, raw))
    .map(([key]) => key)
}

export function pickDefaultChartMetrics(keys: string[]): string[] {
  const ordered: string[] = []
  for (const preferred of PREFERRED_METRIC_ORDER) {
    if (keys.includes(preferred)) ordered.push(preferred)
  }
  for (const key of keys) {
    if (!ordered.includes(key)) ordered.push(key)
  }
  return ordered.slice(0, 3)
}

export function formatChartValue(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return value.toExponential(2)
  if (abs >= 1000) return value.toFixed(0)
  if (abs >= 100) return value.toFixed(1)
  if (abs >= 1) return value.toFixed(2)
  return value.toFixed(3)
}
