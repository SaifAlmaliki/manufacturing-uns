import { describe, expect, it } from 'vitest';
import type { MqttMessage } from '../../types/uns';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import { buildSignalSnapshot } from './plant-summary';

const signal = (over: Partial<GraphqlSubscribedSignal> = {}): GraphqlSubscribedSignal => ({
  serverId: 's1',
  serverName: 'wtp2',
  nodeId: 'ns=3;s=P101',
  browsePath: 'P101/Current',
  displayName: 'Motor current',
  mqttTopic: 'HalabjaWTP/P101/Current',
  subscribed: true,
  ...over,
});

const msg = (topic: string, value: number, ageMs: number): MqttMessage => ({
  id: topic,
  topic,
  payload: { value },
  timestamp: new Date(Date.now() - ageMs).toISOString(),
});

describe('buildSignalSnapshot', () => {
  it('prefers subscribed signals that currently have live feed values', () => {
    const signals = [
      signal({ mqttTopic: 'HalabjaWTP/P101/Current', displayName: 'Current' }),
      signal({ mqttTopic: 'HalabjaWTP/AIT100/Value', displayName: 'Turbidity' }),
      signal({ mqttTopic: 'HalabjaWTP/PT101/Pressure', displayName: 'Pressure' }),
    ];
    const feed = [msg('HalabjaWTP/AIT100/Value', 7.1, 1_000)];
    const snapshot = buildSignalSnapshot(signals, feed, 2);
    expect(snapshot.map((row) => row.label)).toEqual(['Turbidity', 'Current']);
    expect(snapshot[0]?.value).toBe('7.1');
    expect(snapshot[1]?.value).toBe('—');
  });
});
