import { useApolloClient } from '@apollo/client'
import { useCallback, useEffect, useRef } from 'react'
import { useUnsDispatch } from '../../app/UnsProvider'
import { loadChildren } from './expand-to'

export function useTreeQueries() {
  const client = useApolloClient()
  const dispatch = useUnsDispatch()
  const started = useRef(false)

  const loadRoots = useCallback(() => {
    void loadChildren(client, dispatch, '')
  }, [client, dispatch])

  useEffect(() => {
    if (started.current) {
      return
    }
    started.current = true
    loadRoots()
  }, [loadRoots])

  return { loadRoots }
}
