import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { FeedRow } from './feed-row'
import type { FeedItem } from './feed-buffer'

test('uns row shows json preview', () => {
  const item: FeedItem = {
    id: '1',
    topic: 'acme/l1',
    timestamp: 't',
    kind: 'uns',
    preview: { rpm: 1 },
  }
  render(<FeedRow item={item} selectedNamespace={null} onClick={() => undefined} />)
  expect(screen.getByText(/rpm/)).toBeInTheDocument()
})

test('sparkplug row shows badge not json', () => {
  const item: FeedItem = {
    id: '2',
    topic: 'spBv1.0/G/NDATA/E',
    timestamp: 't',
    kind: 'sparkplug',
    preview: null,
  }
  render(<FeedRow item={item} selectedNamespace={null} onClick={() => undefined} />)
  expect(screen.getByText('Sparkplug B (binary)')).toBeInTheDocument()
  expect(screen.queryByText('{')).not.toBeInTheDocument()
})

test('invalid json row', () => {
  const item: FeedItem = {
    id: '3',
    topic: 'acme/l1',
    timestamp: 't',
    kind: 'invalid-json',
    preview: null,
  }
  render(<FeedRow item={item} selectedNamespace={null} onClick={() => undefined} />)
  expect(screen.getByText('invalid JSON')).toBeInTheDocument()
})

test('highlights matching topic', () => {
  const item: FeedItem = {
    id: '4',
    topic: 'acme/l1',
    timestamp: 't',
    kind: 'uns',
    preview: { a: 1 },
  }
  render(<FeedRow item={item} selectedNamespace="acme" onClick={() => undefined} />)
  expect(screen.getByTestId('feed-row').getAttribute('data-highlighted')).toBe('true')
})
