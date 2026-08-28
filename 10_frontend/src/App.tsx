import { ApolloProvider } from '@apollo/client'
import { AppShell } from './features/shell/AppShell'
import { UnsProvider } from './app/UnsProvider'
import { createApolloClient } from './lib/graphql/client'
import { GraphqlConfigError } from './lib/graphql/graphql-url'
import { platformConfig } from './lib/platform/config'

function buildClient() {
  try {
    return createApolloClient()
  } catch (error) {
    return error
  }
}

const clientOrError = buildClient()

export function App() {
  if (clientOrError instanceof GraphqlConfigError) {
    return (
      <main className="p-8">
        <h1>{platformConfig.displayName}</h1>
        <p>{clientOrError.message}</p>
      </main>
    )
  }
  if (clientOrError instanceof Error) {
    throw clientOrError
  }
  return (
    <ApolloProvider client={clientOrError}>
      <UnsProvider>
        <AppShell />
      </UnsProvider>
    </ApolloProvider>
  )
}
