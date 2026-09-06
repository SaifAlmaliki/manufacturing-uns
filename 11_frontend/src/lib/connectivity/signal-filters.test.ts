import { describe, expect, it } from 'vitest'
import { filterSubscribedSignals } from './signal-filters'
import type { GraphqlSubscribedSignal } from '../../services/graphql/types'

const row = (over: Partial<GraphqlSubscribedSignal> = {}): GraphqlSubscribedSignal => ({
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Level',
  displayName: 'Level',
  mqttTopic: 'Plant/T101/Level',
  subscribed: true,
  unitOfMeasure: '°C',
  labels: ['Cycle'],
  ...over,
})

describe('filterSubscribedSignals', () => {
  it('keeps only missing-unit rows when that chip is on', () => {
    const rows = [row(), row({ nodeId: 'n2', unitOfMeasure: null })]
    expect(filterSubscribedSignals(rows, { missingUnit: true }).map((r) => r.nodeId)).toEqual(['n2'])
  })

  it('treats undefined and empty string as missing unit', () => {
    const rows = [
      row({ nodeId: 'undef', unitOfMeasure: undefined }),
      row({ nodeId: 'empty', unitOfMeasure: '' }),
      row({ nodeId: 'null', unitOfMeasure: null }),
      row({ nodeId: 'present', unitOfMeasure: 'bar' }),
    ]
    expect(filterSubscribedSignals(rows, { missingUnit: true }).map((r) => r.nodeId)).toEqual([
      'undef',
      'empty',
      'null',
    ])
  })

  it('matches search case-insensitively on displayName, mqttTopic, nodeId, and serverName', () => {
    const rows = [
      row({ nodeId: 'by-display', displayName: 'Tank Level' }),
      row({ nodeId: 'by-topic', mqttTopic: 'Plant/Tank/Pressure' }),
      row({ nodeId: 'ns=3;s=UniqueNode', displayName: 'Other' }),
      row({ nodeId: 'by-server', serverName: 'LineServer', serverId: 's2' }),
      row({ nodeId: 'no-match', displayName: 'Flow' }),
    ]
    expect(filterSubscribedSignals(rows, { search: 'tank' }).map((r) => r.nodeId)).toEqual([
      'by-display',
      'by-topic',
    ])
    expect(filterSubscribedSignals(rows, { search: 'UNIQUENODE' }).map((r) => r.nodeId)).toEqual([
      'ns=3;s=UniqueNode',
    ])
    expect(filterSubscribedSignals(rows, { search: 'lineserver' }).map((r) => r.nodeId)).toEqual([
      'by-server',
    ])
  })

  it('returns all rows when search is blank', () => {
    const rows = [row({ nodeId: 'a' }), row({ nodeId: 'b' })]
    expect(filterSubscribedSignals(rows, { search: '' })).toHaveLength(2)
    expect(filterSubscribedSignals(rows, { search: '   ' })).toHaveLength(2)
  })

  it('filters by serverId', () => {
    const rows = [
      row({ nodeId: 's1-tag', serverId: 's1' }),
      row({ nodeId: 's2-tag', serverId: 's2', serverName: 'other' }),
    ]
    expect(filterSubscribedSignals(rows, { serverId: 's2' }).map((r) => r.nodeId)).toEqual(['s2-tag'])
  })

  it('filters by semanticClass', () => {
    const rows = [
      row({ nodeId: 'measured', semanticClass: 'MeasuredValue' }),
      row({ nodeId: 'state', semanticClass: 'State' }),
    ]
    expect(
      filterSubscribedSignals(rows, { semanticClass: 'State' }).map((r) => r.nodeId),
    ).toEqual(['state'])
  })

  it('filters by label', () => {
    const rows = [
      row({ nodeId: 'cycle', labels: ['Cycle', 'Alarm'] }),
      row({ nodeId: 'other', labels: ['Alarm'] }),
    ]
    expect(filterSubscribedSignals(rows, { label: 'Cycle' }).map((r) => r.nodeId)).toEqual(['cycle'])
  })

  it('applies all active filters together', () => {
    const rows = [
      row({
        nodeId: 'match',
        serverId: 's1',
        displayName: 'Tank Level',
        unitOfMeasure: null,
        semanticClass: 'MeasuredValue',
        labels: ['Cycle'],
      }),
      row({
        nodeId: 'wrong-server',
        serverId: 's2',
        displayName: 'Tank Level',
        unitOfMeasure: null,
        semanticClass: 'MeasuredValue',
        labels: ['Cycle'],
      }),
    ]
    expect(
      filterSubscribedSignals(rows, {
        search: 'tank',
        serverId: 's1',
        missingUnit: true,
        semanticClass: 'MeasuredValue',
        label: 'Cycle',
      }).map((r) => r.nodeId),
    ).toEqual(['match'])
  })
})
