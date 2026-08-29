import { useSubscription } from '@apollo/client'
import type { RefObject } from 'react'
import { useUnsDispatch } from '../../app/UnsProvider'
import { MQTT_FEED } from '../../lib/graphql/operations'
import type { GraphqlMqttMessage } from '../../lib/graphql/types'

export function useMqttFeed(args: {
  listRef: RefObject<HTMLDivElement | null>
  pinNewest: RefObject<boolean>
}) {
  const dispatch = useUnsDispatch()
  useSubscription<{ getMqttMessages: GraphqlMqttMessage }>(MQTT_FEED, {
    skip: import.meta.env.MODE === 'test' || Boolean(import.meta.env.VITEST),
    variables: { topics: [{ topic: '#' }] },
    onData: ({ data }) => {
      const msg = data.data?.getMqttMessages
      if (!msg) {
        return
      }
      const typename = msg.payload?.__typename
      dispatch({ type: 'conn/ws', ok: true })
      dispatch({
        type: 'feed/mqtt',
        topic: msg.topic,
        typename: typename === 'BytesPayload' || typename === 'JSONPayload' ? typename : 'unknown',
        data:
          msg.payload?.__typename === 'JSONPayload'
            ? msg.payload.data
            : msg.payload?.__typename === 'BytesPayload'
              ? msg.payload.bytesData
              : undefined,
        timestamp: new Date().toISOString(),
      })
      if (args.pinNewest.current && args.listRef.current) {
        args.listRef.current.scrollTop = 0
      }
    },
    onError: () => {
      dispatch({ type: 'conn/ws', ok: false })
    },
    onComplete: () => {
      dispatch({ type: 'conn/ws', ok: false })
    },
  })
}
