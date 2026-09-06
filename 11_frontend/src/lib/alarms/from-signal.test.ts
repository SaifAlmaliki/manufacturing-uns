import { describe, expect, it } from 'vitest'
import type { GraphqlSubscribedSignal } from '../../services/graphql/types'
import { conditionsForDataType, defaultsFromSignal } from './from-signal'

const signal = (over: Partial<GraphqlSubscribedSignal> = {}): GraphqlSubscribedSignal => ({
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Temperature',
  displayName: 'Temperature',
  mqttTopic: 'Plant/Reactor01/Temperature',
  subscribed: true,
  unitOfMeasure: '°C',
  dataType: 'Double',
  labels: [],
  ...over,
})

describe('defaultsFromSignal', () => {
  it('binds the rule to the signal topic and the collector value leaf', () => {
    expect(defaultsFromSignal(signal())).toEqual({
      topic: 'Plant/Reactor01/Temperature',
      metricField: 'value',
      unit: '°C',
      suggestedName: 'Temperature',
      category: 'TEMPERATURE',
      condition: 'GREATER_THAN',
    })
  })

  it('prefixes the suggested name with the linked asset when present', () => {
    expect(
      defaultsFromSignal(signal({ assetDisplayName: 'Reactor 01', displayName: 'Temperature' }))
        .suggestedName,
    ).toBe('Reactor 01 Temperature')
  })

  it('infers category from the topic when the display name is generic', () => {
    expect(
      defaultsFromSignal(
        signal({ displayName: 'PV', mqttTopic: 'Plant/Line/vibration_rms', unitOfMeasure: 'mm/s' }),
      ).category,
    ).toBe('VIBRATION')
  })

  it('uses equals for boolean signals and contains for strings', () => {
    expect(defaultsFromSignal(signal({ dataType: 'Boolean', displayName: 'Running' })).condition).toBe(
      'EQUALS',
    )
    expect(defaultsFromSignal(signal({ dataType: 'String', displayName: 'Batch' })).condition).toBe(
      'CONTAINS',
    )
  })
})

describe('conditionsForDataType', () => {
  it('limits boolean signals to equality checks plus stale timeout', () => {
    expect(conditionsForDataType('Boolean').map((c) => c.value)).toEqual([
      'EQUALS',
      'NOT_EQUALS',
      'STALE_TIMEOUT',
    ])
  })

  it('keeps numeric comparisons for doubles and unknown types', () => {
    expect(conditionsForDataType('Double').map((c) => c.value)).toContain('GREATER_THAN')
    expect(conditionsForDataType(null).map((c) => c.value)).toContain('RANGE_OUTSIDE')
  })
})
