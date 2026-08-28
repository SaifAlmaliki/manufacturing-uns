import { expect, test } from 'vitest'
import { appendFeed, FEED_CAP, type FeedItem } from './feed-buffer'

function item(id: string): FeedItem {
  return { id, topic: `t/${id}`, timestamp: id, kind: 'uns', preview: { n: 1 } }
}

test('pause drops incoming', () => {
  const next = appendFeed([item('1')], item('2'), true)
  expect(next).toHaveLength(1)
  expect(next[0]?.id).toBe('1')
})

test('prepends newest and caps at 500', () => {
  const many = Array.from({ length: FEED_CAP }, (_, i) => item(String(i)))
  const next = appendFeed(many, item('new'), false)
  expect(next).toHaveLength(FEED_CAP)
  expect(next[0]?.id).toBe('new')
  expect(next.at(-1)?.id).toBe(String(FEED_CAP - 2))
})
