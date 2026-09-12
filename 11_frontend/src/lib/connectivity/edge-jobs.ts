/**
 * Poll edge management jobs until they reach a terminal state.
 */

import type { GraphqlConnectivityJob } from '../../services/graphql/types'

const TERMINAL = new Set(['completed', 'failed', 'expired', 'COMPLETED', 'FAILED', 'EXPIRED'])

export function isTerminalJobStatus(status: string): boolean {
  return TERMINAL.has(status) || TERMINAL.has(status.toLowerCase())
}

export async function pollConnectivityJob(
  jobId: string,
  fetchJob: (id: string) => Promise<GraphqlConnectivityJob>,
  options?: { intervalMs?: number; timeoutMs?: number },
): Promise<GraphqlConnectivityJob> {
  const intervalMs = options?.intervalMs ?? 500
  const timeoutMs = options?.timeoutMs ?? 60_000
  const started = Date.now()
  let latest = await fetchJob(jobId)
  while (!isTerminalJobStatus(latest.status)) {
    if (Date.now() - started > timeoutMs) {
      throw new Error(`Job ${jobId} timed out after ${timeoutMs}ms`)
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    latest = await fetchJob(jobId)
  }
  return latest
}

type RawBrowseTag = {
  node_id?: string
  nodeId?: string
  browse_name?: string
  browseName?: string
  display_name?: string
  displayName?: string
  browse_path?: string
  browsePath?: string
  node_class?: string
  nodeClass?: string
  has_children?: boolean
  hasChildren?: boolean
}

export function parseBrowseJobResult(result: unknown): {
  tags: Array<{
    nodeId: string
    browseName: string
    displayName: string
    browsePath: string
    nodeClass: string
    hasChildren: boolean
  }>
  hasMore: boolean
  nextCursor: string | null
} {
  if (!result || typeof result !== 'object') {
    return { tags: [], hasMore: false, nextCursor: null }
  }
  const payload = result as Record<string, unknown>
  const rawTags = Array.isArray(payload.tags) ? (payload.tags as RawBrowseTag[]) : []
  const tags = rawTags.map((tag) => ({
    nodeId: String(tag.nodeId ?? tag.node_id ?? ''),
    browseName: String(tag.browseName ?? tag.browse_name ?? ''),
    displayName: String(tag.displayName ?? tag.display_name ?? tag.browseName ?? tag.browse_name ?? ''),
    browsePath: String(tag.browsePath ?? tag.browse_path ?? ''),
    nodeClass: String(tag.nodeClass ?? tag.node_class ?? 'Variable'),
    hasChildren: Boolean(tag.hasChildren ?? tag.has_children),
  }))
  return {
    tags,
    hasMore: Boolean(payload.has_more ?? payload.hasMore),
    nextCursor: (payload.next_cursor ?? payload.nextCursor ?? null) as string | null,
  }
}

export function parseTestJobResult(result: unknown): { ok: boolean; error: string | null } {
  if (!result || typeof result !== 'object') {
    return { ok: false, error: 'No result payload' }
  }
  const payload = result as Record<string, unknown>
  if (payload.ok === false) {
    return { ok: false, error: String(payload.error_detail ?? payload.error ?? 'Test failed') }
  }
  return { ok: true, error: null }
}
