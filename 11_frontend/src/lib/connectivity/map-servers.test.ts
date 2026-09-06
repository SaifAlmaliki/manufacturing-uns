import { describe, expect, it } from 'vitest'
import {
  CONNECTIVITY_SERVERS_PATH,
  CONNECTIVITY_SIGNALS_PATH,
  connectivityTabFromPath,
  formatBrowseClock,
  formatLastTestedAt,
  formatOpcUaValue,
} from './map-servers'

describe('formatBrowseClock', () => {
  it('prints a 24-hour clock without AM/PM', () => {
    const stamp = formatBrowseClock('2026-09-05T17:47:47.000Z')
    expect(stamp).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    expect(stamp).not.toMatch(/AM|PM/i)
  })

  it('returns an em dash when the stamp is missing', () => {
    expect(formatBrowseClock(null)).toBe('—')
    expect(formatBrowseClock('not-a-date')).toBe('—')
  })
})

describe('formatLastTestedAt', () => {
  it('keeps last-tested stamps in 24-hour form', () => {
    const stamp = formatLastTestedAt('2026-09-05T17:47:47.000Z')
    expect(stamp).not.toMatch(/AM|PM/i)
  })
})

describe('connectivityTabFromPath', () => {
  it('reads servers vs signals from the hash path', () => {
    expect(connectivityTabFromPath(CONNECTIVITY_SIGNALS_PATH)).toBe('signals')
    expect(connectivityTabFromPath(CONNECTIVITY_SERVERS_PATH)).toBe('servers')
    expect(connectivityTabFromPath('/connectivity')).toBe('servers')
    expect(connectivityTabFromPath('/connectivity/')).toBe('servers')
  })
})

describe('formatOpcUaValue', () => {
  it('prints a scalar and dashes a missing reading', () => {
    expect(formatOpcUaValue(12.5)).toBe('12.5')
    expect(formatOpcUaValue(null)).toBe('—')
    expect(formatOpcUaValue(undefined)).toBe('—')
  })
})
