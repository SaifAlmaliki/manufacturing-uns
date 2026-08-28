import { expect, test } from 'vitest'
import { GraphqlConfigError, httpToWs, resolveGraphqlHttpUrl } from './graphql-url'

test('dev uses relative /graphql', () => {
  expect(resolveGraphqlHttpUrl({ prod: false, envUrl: undefined })).toBe('/graphql')
})

test('prod requires VITE_GRAPHQL_URL when no platform default is set', () => {
  expect(() => resolveGraphqlHttpUrl({ prod: true, envUrl: '' })).toThrow(GraphqlConfigError)
  expect(() => resolveGraphqlHttpUrl({ prod: true, envUrl: undefined })).toThrow(GraphqlConfigError)
})

test('prod falls back to platform graphql url', () => {
  expect(
    resolveGraphqlHttpUrl({
      prod: true,
      envUrl: undefined,
      defaultProdUrl: 'http://localhost:8000/graphql',
    }),
  ).toBe('http://localhost:8000/graphql')
})

test('prod http url converts to ws', () => {
  expect(httpToWs('http://localhost:8000/graphql')).toBe('ws://localhost:8000/graphql')
  expect(httpToWs('https://example.com/graphql')).toBe('wss://example.com/graphql')
})

test('relative url uses window location host', () => {
  expect(httpToWs('/graphql', { protocol: 'http:', host: 'localhost:5173' })).toBe(
    'ws://localhost:5173/graphql',
  )
})
