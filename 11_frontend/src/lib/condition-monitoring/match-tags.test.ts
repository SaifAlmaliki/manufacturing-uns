import { describe, expect, it } from 'vitest';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import type { UnsNode } from '../../types/uns';
import {
  collectLoadedDescendants,
  filterTagsBySearch,
  tagInScope,
  tagMatchesNode,
} from './match-tags';

const tag = (over: Partial<GraphqlConnectivityTag> = {}): GraphqlConnectivityTag => ({
  serverId: 's1',
  nodeId: 'ns=3;s=x',
  browsePath: 'Distribution/P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/Telemetry/WaterTreatmentPlant/Distribution/P201/Fault',
  subscribed: true,
  ...over,
});

const node = (topic: string, children: UnsNode[] = []): UnsNode => ({
  topic,
  name: topic.split('/').pop() ?? topic,
  lastUpdated: '',
  isLeaf: children.length === 0,
  children,
});

describe('tagMatchesNode', () => {
  it('matches a remapped MQTT topic by prefix', () => {
    const remapped = tag({
      mqttTopic: 'AcmeWater/Site1/Distribution/Train1/P201/Fault',
      browsePath: 'Distribution/P201/Fault',
    });
    expect(
      tagMatchesNode(remapped, node('AcmeWater/Site1/Distribution/Train1/P201')),
    ).toBe(true);
  });

  it('matches a browse-path subscription by leaf name P201', () => {
    expect(
      tagMatchesNode(tag(), node('AcmeWater/Site1/Distribution/Train1/P201')),
    ).toBe(true);
  });

  it('does not match P202 against a P201 node', () => {
    expect(
      tagMatchesNode(
        tag({
          browsePath: 'Distribution/P202/Speed',
          mqttTopic: 'Server/OpcPlc/Distribution/P202/Speed',
          displayName: 'Speed',
        }),
        node('AcmeWater/Site1/Distribution/Train1/P201'),
      ),
    ).toBe(false);
  });
});

describe('tagInScope', () => {
  const p201 = node('AcmeWater/Site1/Distribution/Train1/P201');
  const p202 = node('AcmeWater/Site1/Distribution/Train1/P202');
  const train1 = node('AcmeWater/Site1/Distribution/Train1', [p201, p202]);
  const p201Tag = tag();
  const p202Tag = tag({
    browsePath: 'Distribution/P202/Speed',
    mqttTopic: 'Server/OpcPlc/Distribution/P202/Speed',
    displayName: 'Speed',
  });

  it('returns every tag when scope is null', () => {
    expect(tagInScope(p201Tag, null)).toBe(true);
    expect(tagInScope(p202Tag, null)).toBe(true);
  });

  it('includes descendant P201 tags when scoped to loaded Train1 and excludes P202 if not a match of Train1 itself', () => {
    expect(tagInScope(p201Tag, train1)).toBe(true);
    expect(tagInScope(p202Tag, train1)).toBe(true);
    expect(tagInScope(p202Tag, p201)).toBe(false);
  });

  it('does not match Train1 by name against a browse path that omits Train1 when children are not loaded', () => {
    const unloaded = node('AcmeWater/Site1/Distribution/Train1');
    expect(tagInScope(p201Tag, unloaded)).toBe(false);
  });
});

describe('collectLoadedDescendants', () => {
  it('walks loaded children only', () => {
    const leaf = node('AcmeWater/Site1/P201');
    const parent = node('AcmeWater/Site1', [leaf]);
    expect(collectLoadedDescendants(parent).map((n) => n.topic)).toEqual([
      'AcmeWater/Site1',
      'AcmeWater/Site1/P201',
    ]);
  });
});

describe('filterTagsBySearch', () => {
  it('matches display name or mqtt topic, case-insensitive', () => {
    const tags = [
      tag(),
      tag({
        displayName: 'Speed',
        mqttTopic: 'Server/OpcPlc/P202/Speed',
        browsePath: 'P202/Speed',
      }),
    ];
    expect(filterTagsBySearch(tags, 'fault')).toHaveLength(1);
    expect(filterTagsBySearch(tags, 'P202')).toHaveLength(1);
    expect(filterTagsBySearch(tags, '')).toHaveLength(2);
  });
});
