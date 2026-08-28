import { ApolloClient, HttpLink, InMemoryCache, split } from '@apollo/client'
import { GraphQLWsLink } from '@apollo/client/link/subscriptions'
import { getMainDefinition } from '@apollo/client/utilities'
import { createClient } from 'graphql-ws'
import { getGraphqlHttpUrl, getGraphqlWsUrl } from './graphql-url'

export function createApolloClient(): ApolloClient<unknown> {
  const httpLink = new HttpLink({ uri: getGraphqlHttpUrl() })
  const wsLink = new GraphQLWsLink(
    createClient({
      url: getGraphqlWsUrl(),
      retryAttempts: Infinity,
      shouldRetry: () => true,
    }),
  )
  const link = split(
    ({ query }) => {
      const def = getMainDefinition(query)
      return def.kind === 'OperationDefinition' && def.operation === 'subscription'
    },
    wsLink,
    httpLink,
  )
  return new ApolloClient({ link, cache: new InMemoryCache() })
}
