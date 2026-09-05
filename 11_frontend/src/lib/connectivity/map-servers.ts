/**
 * Translation between a Connectivity server as the server stores it and as the
 * Assets & Connectivity page renders it.
 *
 * The server spells the protocol enum in upper case (`OPC_UA`); the page's tab keys
 * are lower-snake (`opc_ua`, `modbus_tcp`, …) so a future protocol can land as a tab
 * that says "Not in this slice" without a schema change. Keeping the mapping here is
 * what stops those two vocabularies from leaking into each component.
 */

import type { GraphqlConnectivityServer } from '../../services/graphql/types'

export type ConnectivityTabId =
  | 'opc_ua'
  | 'modbus_tcp'
  | 's7'
  | 'ethernet_ip'
  | 'mqtt'
  | 'sql'

export const PROTOCOL_TABS: { id: ConnectivityTabId; label: string }[] = [
  { id: 'opc_ua', label: 'OPC UA' },
  { id: 'modbus_tcp', label: 'Modbus TCP' },
  { id: 's7', label: 'S7' },
  { id: 'ethernet_ip', label: 'Ethernet/IP' },
  { id: 'mqtt', label: 'MQTT' },
  { id: 'sql', label: 'SQL' },
]

export const PROTOCOLS_IN_SLICE: ConnectivityTabId[] = ['opc_ua']

export function isProtocolInSlice(tab: ConnectivityTabId): boolean {
  return PROTOCOLS_IN_SLICE.includes(tab)
}

const STATUS_DOT: Record<string, string> = {
  connected: 'bg-emerald-500',
  failed: 'bg-rose-500',
  untested: 'bg-zinc-500',
}

export function statusDotClass(lastStatus: string): string {
  return STATUS_DOT[lastStatus] ?? 'bg-zinc-500'
}

export function statusLabel(lastStatus: string): string {
  if (!lastStatus) return 'Untested'
  return lastStatus.charAt(0).toUpperCase() + lastStatus.slice(1)
}

export function formatLastTestedAt(lastTestedAt: string | null | undefined): string {
  if (!lastTestedAt) return '—'
  try {
    const d = new Date(lastTestedAt)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString()
  } catch {
    return '—'
  }
}

/** Clock-only stamp for the browse table — ISO strings are too wide. */
export function formatBrowseClock(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Servers whose name or endpoint contains the query (case-insensitive). */
export function filterServers(
  servers: GraphqlConnectivityServer[],
  query: string,
): GraphqlConnectivityServer[] {
  const q = query.trim().toLowerCase()
  if (!q) return servers
  return servers.filter(
    (s) => s.name.toLowerCase().includes(q) || s.endpoint.toLowerCase().includes(q),
  )
}
