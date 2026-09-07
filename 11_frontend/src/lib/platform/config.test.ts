import { describe, expect, it } from 'vitest'
import { platformConfig } from './config'

describe('platformConfig', () => {
  it('is injected into the test environment', () => {
    expect(platformConfig.graphqlPath).toBe('/graphql')
  })

  it('reports the real dev port, not Grafana&apos;s 3000', () => {
    expect(platformConfig.frontendDevPort).toBe(5173)
  })

  it('reports the agent proxy target for dev', () => {
    expect(platformConfig.agentProxyTarget).toBe('http://localhost:8088')
  })
})
