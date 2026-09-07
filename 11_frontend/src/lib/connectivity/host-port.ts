/**
 * `host:port` endpoint parsing for the protocols that skip the OPC UA `opc.tcp://`
 * URL shape — S7 and EtherNet/IP dial a bare host and port instead.
 */

import type { ConnectivityTabId } from './map-servers'

const HOST_PORT = /^([A-Za-z0-9.-]+):(\d{1,5})$/

export function joinHostPort(host: string, port: string): string {
  return `${host.trim()}:${port.trim()}`
}

export function splitHostPort(endpoint: string): { host: string; port: string } {
  const match = HOST_PORT.exec(endpoint.trim())
  if (!match) return { host: '', port: '' }
  return { host: match[1], port: match[2] }
}

export function isHostPort(endpoint: string): boolean {
  const match = HOST_PORT.exec(endpoint.trim())
  if (!match) return false
  const port = Number(match[2])
  return port >= 1 && port <= 65535
}

const DEFAULT_PORT: Partial<Record<ConnectivityTabId, string>> = {
  s7: '102',
  ethernet_ip: '44818',
}

export function defaultPortFor(protocol: ConnectivityTabId): string {
  return DEFAULT_PORT[protocol] ?? ''
}
