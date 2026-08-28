import { expect, test } from 'vitest'
import { connectionChip, connectionLabel } from './connection'

test('connection chip', () => {
  expect(connectionChip(true, true)).toBe('live')
  expect(connectionChip(true, false)).toBe('degraded')
  expect(connectionChip(false, true)).toBe('degraded')
  expect(connectionChip(false, false)).toBe('down')
})

test('connection labels', () => {
  expect(connectionLabel('live', true, true)).toBe('Live')
  expect(connectionLabel('down', false, false)).toBe('Down')
  expect(connectionLabel('degraded', false, true)).toBe('Degraded — GraphQL queries down')
  expect(connectionLabel('degraded', true, false)).toBe('Degraded — live feed down')
})
