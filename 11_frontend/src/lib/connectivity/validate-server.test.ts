import { describe, expect, it } from 'vitest'
import {
  AUTH_MODE_TO_GQL,
  SECURITY_MODE_TO_GQL,
  SECURITY_POLICY_TO_GQL,
  validateConnectivityServer,
  type ConnectivityServerDraft,
} from './validate-server'

function draft(overrides: Partial<ConnectivityServerDraft> = {}): ConnectivityServerDraft {
  return {
    protocol: 'opc_ua',
    name: 'opcplc',
    endpoint: 'opc.tcp://host.docker.internal:50000/',
    authMode: 'anonymous',
    securityPolicy: 'None',
    securityMode: 'None',
    username: '',
    password: '',
    certificate: '',
    privateKey: '',
    ...overrides,
  }
}

describe('validateConnectivityServer', () => {
  it('accepts anonymous None — the OpcPlc default', () => {
    expect(validateConnectivityServer(draft())).toBeNull()
  })

  it('rejects a protocol that is not in this slice', () => {
    expect(validateConnectivityServer(draft({ protocol: 'modbus_tcp' }))).toMatch(/later/i)
  })

  it('rejects a missing name', () => {
    expect(validateConnectivityServer(draft({ name: '  ' }))).toMatch(/name/i)
  })

  it('rejects an endpoint that is not opc.tcp://host:port', () => {
    expect(validateConnectivityServer(draft({ endpoint: 'https://plc' }))).toMatch(/opc\.tcp/)
  })

  it('rejects username auth without a password', () => {
    expect(
      validateConnectivityServer(draft({ authMode: 'username', username: 'eng', password: '' })),
    ).toMatch(/password/i)
  })

  it('rejects X509 without a security policy', () => {
    expect(
      validateConnectivityServer(
        draft({
          authMode: 'x509',
          certificate: '/certs/client.der',
          privateKey: '/certs/client.key',
        }),
      ),
    ).toMatch(/security policy/i)
  })

  it('rejects a secured channel without cert paths', () => {
    expect(
      validateConnectivityServer(
        draft({ securityPolicy: 'Basic256Sha256', securityMode: 'SignAndEncrypt' }),
      ),
    ).toMatch(/certificate/i)
  })
})

describe('GraphQL vocabulary maps', () => {
  it('covers every catalog auth mode and security value', () => {
    expect(Object.keys(AUTH_MODE_TO_GQL)).toEqual(['anonymous', 'username', 'x509'])
    expect(Object.keys(SECURITY_POLICY_TO_GQL)).toEqual([
      'None',
      'Basic256Sha256',
      'Aes128Sha256RsaOaep',
      'Aes256Sha256RsaPss',
    ])
    expect(Object.keys(SECURITY_MODE_TO_GQL)).toEqual(['None', 'Sign', 'SignAndEncrypt'])
  })
})
