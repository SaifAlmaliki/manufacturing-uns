import { describe, expect, test } from 'vitest'
import { parseJsonPayload } from './payload'
import { isSparkplugTopic, SPARKPLUG_PREFIX } from './sparkplug'
import { isStale } from './stale'
import { childrenTopic, historianTopic, isFeedHighlight, parentNamespace } from './topics'

describe('uns domain helpers', () => {
  test('sparkplug prefix', () => {
    expect(SPARKPLUG_PREFIX).toBe('spBv1.0/')
    expect(isSparkplugTopic('spBv1.0/G/NDATA/E/D')).toBe(true)
    expect(isSparkplugTopic('ent/fac/line')).toBe(false)
  })

  test('topics helpers', () => {
    expect(parentNamespace('ent/fac/line')).toBe('ent/fac')
    expect(parentNamespace('ent')).toBe('')
    expect(childrenTopic('')).toBe('+')
    expect(childrenTopic('ent/fac')).toBe('ent/fac/+')
    expect(historianTopic('ent/fac')).toBe('ent/fac/#')
    expect(isFeedHighlight('ent/fac/line', 'ent/fac')).toBe(true)
    expect(isFeedHighlight('ent/fac', 'ent/fac')).toBe(true)
    expect(isFeedHighlight('other', 'ent/fac')).toBe(false)
  })

  test('parse json payload string or object', () => {
    expect(parseJsonPayload('{"a":1}')).toEqual({ ok: true, value: { a: 1 } })
    expect(parseJsonPayload({ a: 1 })).toEqual({ ok: true, value: { a: 1 } })
    expect(parseJsonPayload('not-json').ok).toBe(false)
  })

  test('stale after 5 minutes', () => {
    const now = Date.parse('2026-08-28T12:00:00Z')
    expect(isStale('2026-08-28T11:54:00Z', now)).toBe(true)
    expect(isStale('2026-08-28T11:56:00Z', now)).toBe(false)
  })
})
