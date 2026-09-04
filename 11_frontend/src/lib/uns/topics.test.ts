import { describe, expect, it } from 'vitest'
import { joinSegments, splitTopic, validateSegment } from './topics'

describe('joinSegments', () => {
  it('joins non-empty segments with the topic separator', () => {
    expect(joinSegments('E', 'S')).toBe('E/S')
  })

  it('drops empty segments so a missing level does not introduce a stray slash', () => {
    expect(joinSegments('E', '', 'A')).toBe('E/A')
  })

  it('returns the empty string when no segment is given', () => {
    expect(joinSegments()).toBe('')
  })
})

describe('splitTopic', () => {
  it('splits a topic on the separator', () => {
    expect(splitTopic('E/S/A')).toEqual(['E', 'S', 'A'])
  })

  it('preserves empty levels because MQTT permits them', () => {
    expect(splitTopic('a//c')).toEqual(['a', '', 'c'])
  })

  it('returns an empty array for the empty topic', () => {
    expect(splitTopic('')).toEqual([])
  })
})

describe('validateSegment', () => {
  it('returns a legal segment unchanged', () => {
    expect(validateSegment('Line1')).toBe('Line1')
  })

  it('throws on the empty string', () => {
    expect(() => validateSegment('')).toThrow()
  })

  it('throws on a segment that contains the separator', () => {
    expect(() => validateSegment('A/B')).toThrow()
  })
})
