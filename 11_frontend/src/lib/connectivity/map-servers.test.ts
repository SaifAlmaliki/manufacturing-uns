import { describe, expect, it } from 'vitest'
import { formatBrowseClock, formatLastTestedAt } from './map-servers'

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
