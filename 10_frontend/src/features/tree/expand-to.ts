import type { ApolloClient } from '@apollo/client'
import type { Dispatch } from 'react'
import type { UnsAction, UnsState } from '../../app/uns-reducer'
import { GET_UNS_NODES } from '../../lib/graphql/operations'
import type { GraphqlUnsNode } from '../../lib/graphql/types'
import { childrenTopic } from '../../lib/uns/topics'
import { graphqlNodesToRecords } from './graphql-nodes'

export async function loadChildren(
  client: ApolloClient<unknown>,
  dispatch: Dispatch<UnsAction>,
  parent: string,
): Promise<boolean> {
  dispatch({ type: 'tree/load-start', parent })
  try {
    const result = await client.query<{ getUnsNodes: GraphqlUnsNode[] }>({
      query: GET_UNS_NODES,
      variables: { topics: [{ topic: childrenTopic(parent) }] },
      fetchPolicy: 'network-only',
    })
    dispatch({
      type: 'tree/load-ok',
      parent,
      nodes: graphqlNodesToRecords(result.data.getUnsNodes ?? []),
    })
    return true
  } catch {
    dispatch({
      type: 'tree/load-err',
      parent,
      message: "Can't reach GraphQL",
    })
    return false
  }
}

export async function expandToNamespace(
  getState: () => UnsState,
  dispatch: Dispatch<UnsAction>,
  client: ApolloClient<unknown>,
  namespace: string,
): Promise<void> {
  const segments = namespace.split('/').filter(Boolean)
  let prefix = ''
  for (const segment of segments) {
    const parent = prefix
    prefix = prefix ? `${prefix}/${segment}` : segment
    const state = getState()
    if (!state.tree.nodes[prefix]) {
      const ok = await loadChildren(client, dispatch, parent)
      if (!ok) {
        return
      }
    }
    dispatch({ type: 'tree/expand', namespace: parent })
  }
  dispatch({ type: 'ui/select-node', namespace })
}
