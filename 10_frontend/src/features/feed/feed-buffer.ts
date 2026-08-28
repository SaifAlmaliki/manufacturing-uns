export const FEED_CAP = 500

export type FeedKind = 'uns' | 'sparkplug' | 'invalid-json'

export type FeedItem = {
  id: string
  topic: string
  timestamp: string
  kind: FeedKind
  preview: unknown | null
}

export function appendFeed(items: FeedItem[], next: FeedItem, paused: boolean): FeedItem[] {
  if (paused) {
    return items
  }
  const out = [next, ...items]
  return out.length > FEED_CAP ? out.slice(0, FEED_CAP) : out
}
