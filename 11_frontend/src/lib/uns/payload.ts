export type ParsePayloadResult = { ok: true; value: unknown } | { ok: false }

export function parseJsonPayload(data: unknown): ParsePayloadResult {
  if (data === null || data === undefined) {
    return { ok: false }
  }
  if (typeof data === 'object') {
    return { ok: true, value: data }
  }
  if (typeof data !== 'string') {
    return { ok: false }
  }
  try {
    return { ok: true, value: JSON.parse(data) }
  } catch {
    return { ok: false }
  }
}
