import { expect, test } from 'vitest'
import { loadPlatformSettings } from './settings'

test('loads graphql url and frontend ports from root conf/settings.yaml', () => {
  const settings = loadPlatformSettings()
  expect(settings.graphqlUrl).toBe('http://localhost:8000/graphql')
  expect(settings.graphqlProxyTarget).toBe('http://localhost:8000')
  expect(settings.frontendDevPort).toBe(5173)
  expect(settings.frontendComposePort).toBe(8088)
  expect(settings.displayName).toBe('Unified Namespace')
  expect(settings.instanceName).toBe('Instance01')
})
