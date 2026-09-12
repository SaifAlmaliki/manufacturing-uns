import { describe, expect, it } from 'vitest'
import {
  connectionHealthLabel,
  discoverySupported,
  edgeConnectionState,
  edgePhaseLabel,
  edgeSupportsProtocol,
  isCloudEdgeMode,
  isEdgeHeartbeatStale,
  normalizeAppliedPhase,
  revisionLagLabel,
  saveDoesNotImplyConnected,
} from './edge-status'

describe('edge-status', () => {
  it('detects cloud edge mode when devices are registered', () => {
    expect(isCloudEdgeMode([])).toBe(false)
    expect(
      isCloudEdgeMode([
        {
          edgeId: 'edge-01',
          displayName: 'Site edge',
          status: 'active',
          desiredRevision: 1,
          appliedRevision: 1,
          appliedPhase: 'applied',
        },
      ]),
    ).toBe(true)
  })

  it('labels reconciliation phases', () => {
    expect(edgePhaseLabel('waiting_for_routes')).toBe('Waiting for routes')
    expect(edgePhaseLabel('applying')).toBe('Applying')
    expect(normalizeAppliedPhase('applied')).toBe('applied')
  })

  it('reports revision lag', () => {
    expect(revisionLagLabel(3, 3)).toBe('In sync')
    expect(revisionLagLabel(4, 2)).toBe('2 revisions behind')
  })

  it('marks stale heartbeats offline', () => {
    const now = Date.parse('2026-09-12T12:00:00.000Z')
    expect(
      isEdgeHeartbeatStale('2026-09-12T11:59:30.000Z', now, 120_000),
    ).toBe(false)
    expect(
      isEdgeHeartbeatStale('2026-09-12T11:55:00.000Z', now, 120_000),
    ).toBe(true)
    expect(edgeConnectionState({ status: 'active', lastSeen: null }, now)).toBe('offline')
    expect(edgeConnectionState({ status: 'revoked', lastSeen: null }, now)).toBe('revoked')
  })

  it('checks protocol capability and discovery support', () => {
    const capabilities = { protocols: ['opc_ua', 'modbus'] }
    expect(edgeSupportsProtocol(capabilities, 'modbus_tcp')).toBe(true)
    expect(edgeSupportsProtocol(capabilities, 's7')).toBe(false)
    expect(discoverySupported(capabilities, 'opc_ua')).toBe(true)
    expect(discoverySupported(capabilities, 's7')).toBe(false)
    expect(
      discoverySupported(
        { protocols: ['opc_ua'], discovery: { opc_ua: false } },
        'opc_ua',
      ),
    ).toBe(false)
  })

  it('separates connection health from reconciliation', () => {
    expect(connectionHealthLabel('pending')).toBe('Pending')
    expect(saveDoesNotImplyConnected(true)).toMatch(/explicit Test/)
    expect(saveDoesNotImplyConnected(false)).toBeNull()
  })
})
