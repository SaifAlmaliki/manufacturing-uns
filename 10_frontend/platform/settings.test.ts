import { expect, test } from 'vitest'
import { loadPlatformSettings, platformSettingsFromConfig } from './settings'

test('loads graphql url and frontend ports from root conf/settings.yaml', () => {
  const settings = loadPlatformSettings()
  expect(settings.graphqlUrl).toBe('http://localhost:8000/graphql')
  expect(settings.graphqlProxyTarget).toBe('http://localhost:8000')
  expect(settings.frontendDevPort).toBe(5173)
  expect(settings.frontendComposePort).toBe(8088)
  expect(settings.displayName).toBe('Covestro UNS')
  expect(settings.instanceName).toBe('Instance01')
  expect(settings.organizationName).toBe('CovestroAG')
})

test('uses built-in defaults when settings.yaml is not in the build context', () => {
  const settings = platformSettingsFromConfig()

  expect(settings.graphqlUrl).toBe('http://localhost:8000/graphql')
  expect(settings.graphqlProxyTarget).toBe('http://localhost:8000')
  expect(settings.frontendDevPort).toBe(5173)
  expect(settings.frontendComposePort).toBe(8088)
  expect(settings.displayName).toBe('Unified Namespace')
  expect(settings.instanceName).toBe('default')
})
