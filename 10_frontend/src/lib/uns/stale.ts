const FIVE_MINUTES_MS = 5 * 60 * 1000

export function isStale(lastUpdatedIso: string, nowMs: number): boolean {
  const then = Date.parse(lastUpdatedIso)
  if (Number.isNaN(then)) {
    return false
  }
  return nowMs - then > FIVE_MINUTES_MS
}
