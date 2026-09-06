import { describe, expect, it } from 'vitest'
import {
  GET_CONNECTIVITY_SERVERS_QUERY,
  GET_SUBSCRIBED_SIGNALS_QUERY,
  SAVE_UNIT_OF_MEASURE_MUTATION,
  UPDATE_CONNECTIVITY_TAG_MUTATION,
} from './queries'

describe('signal context documents', () => {
  it('asks for unitOfMeasure on subscribed signals', () => {
    expect(GET_SUBSCRIBED_SIGNALS_QUERY).toMatch(/unitOfMeasure/)
    expect(UPDATE_CONNECTIVITY_TAG_MUTATION).toMatch(/updateConnectivityTag/)
    expect(SAVE_UNIT_OF_MEASURE_MUTATION).toMatch(/saveUnitOfMeasure/)
  })

  it('asks for unitOfMeasure on connectivity servers', () => {
    expect(GET_CONNECTIVITY_SERVERS_QUERY).toMatch(/unitOfMeasure/)
  })
})
