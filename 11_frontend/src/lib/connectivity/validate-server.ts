/**
 * Client-side checks for an OPC UA server draft, before GraphQL is called.
 * The catalog repeats the same rules in ConnectivityServerSpec.validate.
 */

export const CONNECTIVITY_AUTH_MODES = ['anonymous', 'username', 'x509'] as const
export const CONNECTIVITY_SECURITY_POLICIES = [
  'None',
  'Basic256Sha256',
  'Aes128Sha256RsaOaep',
  'Aes256Sha256RsaPss',
] as const
export const CONNECTIVITY_SECURITY_MODES = ['None', 'Sign', 'SignAndEncrypt'] as const

export type ConnectivityAuthMode = (typeof CONNECTIVITY_AUTH_MODES)[number]
export type ConnectivitySecurityPolicy = (typeof CONNECTIVITY_SECURITY_POLICIES)[number]
export type ConnectivitySecurityMode = (typeof CONNECTIVITY_SECURITY_MODES)[number]

/** GraphQL enum names for `ConnectivityServerInput`. Values stay in Postgres as the catalog strings. */
export const AUTH_MODE_TO_GQL = {
  anonymous: 'ANONYMOUS',
  username: 'USERNAME',
  x509: 'X509',
} as const

export const SECURITY_POLICY_TO_GQL = {
  None: 'NONE',
  Basic256Sha256: 'BASIC256_SHA256',
  Aes128Sha256RsaOaep: 'AES128_SHA256_RSA_OAEP',
  Aes256Sha256RsaPss: 'AES256_SHA256_RSA_PSS',
} as const

export const SECURITY_MODE_TO_GQL = {
  None: 'NONE',
  Sign: 'SIGN',
  SignAndEncrypt: 'SIGN_AND_ENCRYPT',
} as const

export type ConnectivityServerDraft = {
  protocol: string
  name: string
  endpoint: string
  authMode: ConnectivityAuthMode
  securityPolicy: ConnectivitySecurityPolicy
  securityMode: ConnectivitySecurityMode
  username: string
  password: string
  certificate: string
  privateKey: string
  serverCertificate?: string
}

const ENDPOINT = /^opc\.tcp:\/\/[^\s\/:]+:\d{1,5}(\/.*)?$/

export function validateConnectivityServer(draft: ConnectivityServerDraft): string | null {
  if (draft.protocol !== 'opc_ua') {
    return 'OPC UA is the only protocol this slice serves. The others land later.'
  }
  if (!draft.name.trim()) return 'Name is required.'
  const endpoint = draft.endpoint.trim()
  if (!endpoint) return 'Endpoint is required.'
  if (!ENDPOINT.test(endpoint)) {
    return 'Endpoint must be opc.tcp://host:port'
  }
  if (draft.securityPolicy === 'None' && draft.securityMode !== 'None') {
    return 'Security mode must be None when the policy is None.'
  }
  if (draft.securityPolicy !== 'None' && draft.securityMode === 'None') {
    return 'Choose Sign or SignAndEncrypt when a security policy is set.'
  }
  if (draft.securityPolicy !== 'None' && (!draft.certificate.trim() || !draft.privateKey.trim())) {
    return 'Certificate and private key paths are required for a secured channel.'
  }
  if (draft.authMode === 'username') {
    if (!draft.username.trim() || !draft.password) {
      return 'Username and password are required.'
    }
  }
  if (draft.authMode === 'x509') {
    if (!draft.certificate.trim() || !draft.privateKey.trim()) {
      return 'Certificate and private key paths are required for X509 authentication.'
    }
    if (draft.securityPolicy === 'None') {
      return 'X509 authentication needs a security policy other than None.'
    }
  }
  return null
}
