import { describe, expect, it } from 'vitest'
import { platformSettingsFromConfig } from '../../../platform/settings'

describe('platformSettingsFromConfig auth values', () => {
  it('reads the realm from the auth block', () => {
    const settings = platformSettingsFromConfig({
      auth: {
        realm: 'uns',
        base_url: 'http://localhost:8088/auth',
        issuer: 'http://localhost:8088/auth/realms/uns',
        console_client_id: 'uns-console',
      },
    })

    expect(settings.authRealm).toBe('uns')
    expect(settings.authBaseUrl).toBe('http://localhost:8088/auth')
    expect(settings.authIssuer).toBe('http://localhost:8088/auth/realms/uns')
    expect(settings.authClientId).toBe('uns-console')
  })

  it('falls back to the compose origin when conf is unreadable', () => {
    // loadPlatformSettings() calls this with {} when it finds no settings.yaml. A console
    // that silently got an empty authority would redirect to nowhere and look like a
    // Keycloak outage, so the fallback has to be the real compose URL.
    const settings = platformSettingsFromConfig({})

    expect(settings.authIssuer).toBe('http://localhost:8088/auth/realms/uns')
    expect(settings.authClientId).toBe('uns-console')
    expect(settings.productName).toBe('Industrial Intelligence Platform')
    expect(settings.productShortName).toBe('IIP')
    expect(settings.consoleName).toBe('IIP Console')
    expect(settings.examplePublicHost).toBe('iip.example.com')
  })

  it('reads product chrome from the platform block', () => {
    const settings = platformSettingsFromConfig({
      platform: {
        product_name: 'Acme Intelligence',
        product_short_name: 'AIM',
        example_public_host: 'aim.example.com',
      },
    })

    expect(settings.productName).toBe('Acme Intelligence')
    expect(settings.productShortName).toBe('AIM')
    expect(settings.consoleName).toBe('AIM Console')
    expect(settings.examplePublicHost).toBe('aim.example.com')
  })
})
