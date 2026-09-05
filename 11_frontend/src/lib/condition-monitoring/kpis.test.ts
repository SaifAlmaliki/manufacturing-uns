import { describe, expect, it } from 'vitest';
import type { ActiveAlarm } from '../../types/alarm';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import { alarmMatchesTag, conditionKpis } from './kpis';
import type { Sample } from './series';

const tag = (over: Partial<GraphqlConnectivityTag> = {}): GraphqlConnectivityTag => ({
  serverId: 's1',
  nodeId: 'n1',
  browsePath: 'P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/P201/Fault',
  subscribed: true,
  ...over,
});

const alarm = (over: Partial<ActiveAlarm> = {}): ActiveAlarm => ({
  id: 'a1',
  ruleId: 'r1',
  ruleName: 'fault',
  topic: 'AcmeWater/Site1/Distribution/Train1/P201/Fault',
  severity: 'CRITICAL',
  category: 'SAFETY',
  conditionDescription: '',
  currentValue: true,
  status: 'ACTIVE_UNACK',
  triggeredAt: '',
  targetRoles: ['engineer'],
  ...over,
});

describe('alarmMatchesTag', () => {
  it('matches by leaf name when the alarm is on a UNS path', () => {
    expect(alarmMatchesTag(alarm().topic, tag())).toBe(true);
  });

  it('matches by prefix when the alarm topic is the mqtt topic', () => {
    expect(alarmMatchesTag('Server/OpcPlc/P201/Fault', tag())).toBe(true);
  });
});

describe('conditionKpis', () => {
  it('counts in view, live, faults on, unacked and critical', () => {
    const fault = tag();
    const speed = tag({
      displayName: 'Speed',
      mqttTopic: 'Server/OpcPlc/P201/Speed',
      browsePath: 'P201/Speed',
      nodeId: 'n2',
    });
    const latest: Record<string, Sample> = {
      [fault.mqttTopic]: { t: 1, v: 1, quality: null, boolean: true },
      [speed.mqttTopic]: { t: 1, v: 12, quality: null, boolean: false },
    };
    const kpis = conditionKpis({
      tags: [fault, speed],
      latestByTopic: latest,
      liveTopics: new Set([speed.mqttTopic]),
      alarms: [alarm(), alarm({ id: 'a2', status: 'ACTIVE_ACK', severity: 'HIGH' })],
    });
    expect(kpis).toEqual({ inView: 2, live: 1, faultsOn: 1, unacked: 1, critical: 1 });
  });
});
