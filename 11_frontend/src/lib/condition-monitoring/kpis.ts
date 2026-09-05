import type { ActiveAlarm } from '../../types/alarm';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import { pathSegments } from './match-tags';
import type { Sample } from './series';

export type ConditionKpis = {
  inView: number;
  live: number;
  faultsOn: number;
  unacked: number;
  critical: number;
};

export function alarmMatchesTag(alarmTopic: string, tag: GraphqlConnectivityTag): boolean {
  if (alarmTopic === tag.mqttTopic || alarmTopic.startsWith(`${tag.mqttTopic}/`)) return true;
  if (tag.mqttTopic === alarmTopic || tag.mqttTopic.startsWith(`${alarmTopic}/`)) return true;
  const alarmLeaf = pathSegments(alarmTopic).at(-1);
  const tagLeaf = pathSegments(tag.mqttTopic).at(-1);
  const browseLeaf = pathSegments(tag.browsePath).at(-1);
  if (!alarmLeaf) return false;
  return alarmLeaf === tagLeaf || alarmLeaf === browseLeaf || alarmLeaf === tag.displayName;
}

function isFaultTag(tag: GraphqlConnectivityTag): boolean {
  const leaf = pathSegments(tag.mqttTopic).at(-1) ?? '';
  return tag.displayName.toLowerCase() === 'fault' || leaf.toLowerCase() === 'fault';
}

export function conditionKpis(args: {
  tags: GraphqlConnectivityTag[];
  latestByTopic: Record<string, Sample | undefined>;
  liveTopics: Set<string>;
  alarms: ActiveAlarm[];
}): ConditionKpis {
  const { tags, latestByTopic, liveTopics, alarms } = args;
  const faultsOn = tags.filter((tag) => {
    if (!isFaultTag(tag)) return false;
    const latest = latestByTopic[tag.mqttTopic];
    return latest !== undefined && latest.v === 1;
  }).length;
  const matching = alarms.filter((alarm) => tags.some((tag) => alarmMatchesTag(alarm.topic, tag)));
  const unacked = matching.filter(
    (alarm) => alarm.status === 'ACTIVE_UNACK' || alarm.status === 'CLEARED_UNACK',
  );
  return {
    inView: tags.length,
    live: tags.filter((tag) => liveTopics.has(tag.mqttTopic)).length,
    faultsOn,
    unacked: unacked.length,
    critical: unacked.filter((alarm) => alarm.severity === 'CRITICAL').length,
  };
}
