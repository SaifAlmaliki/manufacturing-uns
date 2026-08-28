import { expect, test } from 'vitest'
import { initialUnsState, unsReducer } from './uns-reducer'

test('paused feed does not grow', () => {
  let state = unsReducer(initialUnsState(), { type: 'feed/pause', paused: true })
  state = unsReducer(state, {
    type: 'feed/mqtt',
    topic: 'acme/l1',
    typename: 'JSONPayload',
    data: { rpm: 1 },
    timestamp: '2026-08-28T12:00:00Z',
    id: 'm1',
  })
  expect(state.feed).toHaveLength(0)
})

test('select node clears historic event', () => {
  let state = unsReducer(initialUnsState(), {
    type: 'ui/select-historic-event',
    event: {
      topic: 'acme/l1',
      timestamp: '2026-08-28T12:00:00Z',
      publisher: 'plc',
      payload: { rpm: 1 },
    },
  })
  state = unsReducer(state, { type: 'ui/select-node', namespace: 'acme/l1' })
  expect(state.selectedNamespace).toBe('acme/l1')
  expect(state.historicEvent).toBeNull()
})

test('sparkplug mqtt does not create a tree node', () => {
  const state = unsReducer(initialUnsState(), {
    type: 'feed/mqtt',
    topic: 'spBv1.0/G/NDATA/E',
    typename: 'BytesPayload',
    data: 'abc',
    timestamp: '2026-08-28T12:00:00Z',
    id: 'sp1',
  })
  expect(state.feed[0]?.kind).toBe('sparkplug')
  expect(state.tree.nodes['spBv1.0/G/NDATA/E']).toBeUndefined()
})

test('uns mqtt patches a loaded node', () => {
  let state = unsReducer(initialUnsState(), {
    type: 'tree/load-ok',
    parent: '',
    nodes: [
      {
        nodeName: 'l1',
        nodeType: 'LINE',
        namespace: 'acme/l1',
        payload: { rpm: 1 },
        created: '2026-01-01T00:00:00Z',
        lastUpdated: '2026-01-01T00:00:00Z',
      },
    ],
  })
  state = unsReducer(state, {
    type: 'feed/mqtt',
    topic: 'acme/l1',
    typename: 'JSONPayload',
    data: { rpm: 9 },
    timestamp: '2026-08-28T12:00:00Z',
    id: 'm2',
  })
  expect(state.tree.nodes['acme/l1']?.payload).toEqual({ rpm: 9 })
  expect(state.feed[0]?.kind).toBe('uns')
})
