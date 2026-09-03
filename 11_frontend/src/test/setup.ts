import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * No test may reach the network. A test that needs GraphQL stubs `fetch` itself; a test
 * that forgets to gets a named failure here rather than a timeout against a real port.
 */
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error('Unstubbed fetch in a test. Stub it, or mock the client method.')
    }),
  )
  vi.stubGlobal(
    'WebSocket',
    class {
      constructor() {
        throw new Error('Unstubbed WebSocket in a test. Frontend tests never open one.')
      }
    },
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
