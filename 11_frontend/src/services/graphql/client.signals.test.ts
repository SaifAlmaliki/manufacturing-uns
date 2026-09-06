import { describe, expect, it } from 'vitest'
import {
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
})
