import { useApolloClient } from '@apollo/client'
import { useRef } from 'react'
import { useUnsDispatch, useUnsState } from '../../app/UnsProvider'
import { Button } from '../../components/ui/button'
import { expandToNamespace } from '../tree/expand-to'
import { FeedRow } from './feed-row'
import { useMqttFeed } from './useMqttFeed'

export function FeedPanel() {
  const state = useUnsState()
  const dispatch = useUnsDispatch()
  const client = useApolloClient()
  const stateRef = useRef(state)
  stateRef.current = state
  const listRef = useRef<HTMLDivElement>(null)
  const pinNewest = useRef(true)
  useMqttFeed({ listRef, pinNewest })

  return (
    <section aria-label="live feed" className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-console-border px-3 py-2">
        <h2 className="text-xs uppercase tracking-wide text-console-muted">Live feed</h2>
        <Button type="button" onClick={() => dispatch({ type: 'feed/pause', paused: !state.feedPaused })}>
          {state.feedPaused ? 'Resume' : 'Pause'}
        </Button>
      </div>
      <div
        ref={listRef}
        className="flex-1 overflow-auto"
        onScroll={(event) => {
          pinNewest.current = event.currentTarget.scrollTop < 8
        }}
      >
        {state.feed.length === 0 ? (
          <p className="px-3 py-4 text-sm text-console-muted">No messages yet.</p>
        ) : (
          state.feed.map((item) => (
            <FeedRow
              key={item.id}
              item={item}
              selectedNamespace={state.selectedNamespace}
              onClick={() => {
                if (item.kind === 'sparkplug') {
                  return
                }
                void expandToNamespace(() => stateRef.current, dispatch, client, item.topic)
              }}
            />
          ))
        )}
      </div>
    </section>
  )
}
