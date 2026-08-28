export function numericLeafPaths(value: unknown, prefix = ''): string[] {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return prefix ? [prefix] : []
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, i) =>
      numericLeafPaths(item, prefix ? `${prefix}[${i}]` : `[${i}]`),
    )
  }
  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => {
      const path = prefix ? `${prefix}.${k}` : k
      return numericLeafPaths(v, path)
    })
  }
  return []
}

export function getNumericPath(value: unknown, path: string): number | undefined {
  const tokens = [...path.matchAll(/([^[.\]]+)|\[(\d+)\]/g)]
  let current: unknown = value
  for (const token of tokens) {
    if (token[1] !== undefined) {
      if (current === null || typeof current !== 'object' || Array.isArray(current)) {
        return undefined
      }
      current = (current as Record<string, unknown>)[token[1]]
    } else if (token[2] !== undefined) {
      if (!Array.isArray(current)) {
        return undefined
      }
      current = current[Number(token[2])]
    }
  }
  return typeof current === 'number' && Number.isFinite(current) ? current : undefined
}
