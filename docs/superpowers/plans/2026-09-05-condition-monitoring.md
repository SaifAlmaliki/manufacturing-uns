# Condition Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `#/tree` with `#/condition-monitoring`: reused Namespace Tree, one card per subscribed catalog tag, historian lookback plus a dedicated MQTT live tail, Graph | Table, and zone scope.

**Architecture:** Frontend only. Catalog from `getConnectivityServers`, lookback from `getHistoricEvents`, live tail from `subscribeMqttMessages` on each tag’s `mqttTopic`. Match tags to the ISA-95 tree by prefix, then by equipment / leaf name. No new GraphQL types, no Grafana on this route, no second OPC client in the browser.

**Tech Stack:** React 19, TypeScript 5.8, Vite 6, Tailwind 4, react-router 7 (`HashRouter`), Vitest 3 + Testing Library, existing console primitives. SVG charts in this feature folder — no new chart dependency unless a task proves axes/hover cannot ship without one.

**Spec:** `docs/superpowers/specs/2026-09-05-condition-monitoring-design.md`

## Global Constraints

- **Browser talks to GraphQL only** — `POST /graphql`, `WS /graphql`. No MQTT, OPC UA, Timescale, or Grafana iframe on this page.
- **Do not invent GraphQL fields.** Use `unsGraphQLClient.getConnectivityServers`, `getHistoricEvents`, `subscribeMqttMessages` only.
- **Reuse `UnsTreeView`.** Do not fork a second tree. Selection stays on `UNSContext.selectedNode`.
- **Cards = `subscribed: true` catalog tags.** Tree selection never creates cards; it only scopes visibility.
- **Name matching** is prefix first, then last-segment / browsePath segment equality. Two assets named `P201` share name-matched tags until topics are remapped. Remapping is out of scope.
- **Default scope is all subscribed.** Tree click scopes to that node and **currently loaded** descendants. **All signals** clears scope only (does not clear `selectedNode`).
- **Time range:** 15m / 60m / 4h / 24h. Default **60m**.
- **Booleans:** store 0/1, **step** chart, table is **transitions** only, cap **200** rows. Numerics: continuous line, timestamp + value, cap **200**. Render at most **1500** chart points.
- **Do not invent GOOD quality.** Missing quality renders `—`.
- **Catalog error is not an empty plant.** If `getConnectivityServers` throws, show the real message.
- **Alarm chips navigate to `#/alerts`.** This page does not ack, silence, or edit rules.
- **English only.** Compact console layout: `PageContent fullWidth`, header title only, no in-page title banner.
- **Every behaviour gets a Vitest test** with GraphQL mocked at `unsGraphQLClient`. No live broker.

---

## File Structure

```
11_frontend/src/
  App.tsx                                              MODIFY  /condition-monitoring + /tree redirect
  components/
    layout/Sidebar.tsx                                 MODIFY  label + path
    common/Header.tsx                                  MODIFY  getPageHeading
    home/UnsTreeView.tsx                               REUSE   no fork
    condition-monitoring/
      ConditionMonitoringView.tsx                      CREATE  page shell
      ConditionMonitoringView.test.tsx                 CREATE
      SignalCard.tsx                                   CREATE  Graph | Table
      SignalCard.test.tsx                              CREATE
      SignalChart.tsx                                  CREATE  SVG line / step
      SignalChart.test.tsx                             CREATE
  lib/condition-monitoring/
    match-tags.ts                                      CREATE  prefix + leaf match, scope
    match-tags.test.ts                                 CREATE
    series.ts                                          CREATE  extract, merge, transitions, downsample
    series.test.ts                                     CREATE
    kpis.ts                                            CREATE  in view / live / faults / alarms
    kpis.test.ts                                       CREATE
    time-range.ts                                      CREATE  presets → ISO window
    time-range.test.ts                                 CREATE
  context/AuthContext.tsx                              KEEP    tabId `home` → uns_tree
```

`PayloadInspector` and `LiveMqttFeed` stay on disk; this route does not mount them.

---

### Task 1: Name matching and zone scope

**Files:**
- Create: `11_frontend/src/lib/condition-monitoring/match-tags.ts`
- Test: `11_frontend/src/lib/condition-monitoring/match-tags.test.ts`

**Interfaces:**
- Consumes: `GraphqlConnectivityTag` from `11_frontend/src/services/graphql/types.ts`; `UnsNode` from `11_frontend/src/types/uns.ts`
- Produces:
  - `pathSegments(topic: string): string[]`
  - `tagMatchesNode(tag: GraphqlConnectivityTag, node: UnsNode): boolean`
  - `collectLoadedDescendants(node: UnsNode): UnsNode[]` — node plus loaded children, recursive
  - `tagInScope(tag: GraphqlConnectivityTag, scope: UnsNode | null): boolean` — `null` scope = all tags
  - `filterTagsBySearch(tags: GraphqlConnectivityTag[], search: string): GraphqlConnectivityTag[]`

- [ ] **Step 1: Write the failing test**

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/lib/condition-monitoring/match-tags.test.ts`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./match-tags`

- [ ] **Step 3: Write minimal implementation**

```ts
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import type { UnsNode } from '../../types/uns';

export function pathSegments(topic: string): string[] {
  return topic.split('/').filter(Boolean);
}

export function tagMatchesNode(tag: GraphqlConnectivityTag, node: UnsNode): boolean {
  const topic = tag.mqttTopic;
  if (topic === node.topic || topic.startsWith(`${node.topic}/`)) {
    return true;
  }
  const leaf = pathSegments(node.topic).at(-1);
  if (!leaf) return false;
  const haystack = [...pathSegments(tag.mqttTopic), ...pathSegments(tag.browsePath)];
  return haystack.includes(leaf);
}

export function collectLoadedDescendants(node: UnsNode): UnsNode[] {
  const out: UnsNode[] = [node];
  for (const child of node.children ?? []) {
    out.push(...collectLoadedDescendants(child));
  }
  return out;
}

export function tagInScope(tag: GraphqlConnectivityTag, scope: UnsNode | null): boolean {
  if (scope === null) return true;
  return collectLoadedDescendants(scope).some((node) => tagMatchesNode(tag, node));
}

export function filterTagsBySearch(
  tags: GraphqlConnectivityTag[],
  search: string,
): GraphqlConnectivityTag[] {
  const q = search.trim().toLowerCase();
  if (!q) return tags;
  return tags.filter(
    (tag) =>
      tag.displayName.toLowerCase().includes(q) || tag.mqttTopic.toLowerCase().includes(q),
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/lib/condition-monitoring/match-tags.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/condition-monitoring/match-tags.ts 11_frontend/src/lib/condition-monitoring/match-tags.test.ts
git commit -m "feat(condition-monitoring): match subscribed tags to UNS nodes by prefix and leaf name"
```

---

### Task 2: Series — extract, merge, transitions, downsample

**Files:**
- Create: `11_frontend/src/lib/condition-monitoring/series.ts`
- Test: `11_frontend/src/lib/condition-monitoring/series.test.ts`

**Interfaces:**
- Consumes: `HistoricEvent`, `MqttMessage` from `11_frontend/src/types/uns.ts`
- Produces:
  - `export type Sample = { t: number; v: number; quality: string | null; boolean: boolean }`
  - `extractSample(payload: unknown, timestamp: string): Sample | null`
  - `mergeSeries(historian: Sample[], live: Sample[], fromMs: number, toMs: number): Sample[]`
  - `numericTableRows(samples: Sample[], cap?: number): Sample[]` — newest first, default cap 200
  - `booleanTransitions(samples: Sample[], cap?: number): { t: number; from: number; to: number }[]`
  - `downsample(samples: Sample[], maxPoints?: number): Sample[]` — default 1500, min/max buckets
  - `isBooleanPayload(payload: unknown): boolean`

OPC UA collector payloads look like `{ value: 1.35, timestamp: "...", source: "..." }` after `graphqlHistoricalEventToHistoricEvent`. Prefer `value`, then a bare number/boolean payload.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import {
  booleanTransitions,
  downsample,
  extractSample,
  isBooleanPayload,
  mergeSeries,
  numericTableRows,
} from './series';

describe('extractSample', () => {
  it('reads collector { value } and a bare number', () => {
    const a = extractSample({ value: 1.35 }, '2026-09-05T17:20:00.000Z');
    expect(a?.v).toBe(1.35);
    expect(a?.boolean).toBe(false);
    const b = extractSample(42, '2026-09-05T17:20:00.000Z');
    expect(b?.v).toBe(42);
  });

  it('stores booleans as 0/1 and reads quality when present', () => {
    const s = extractSample({ value: true, quality: 'GOOD' }, '2026-09-05T17:20:00.000Z');
    expect(s?.v).toBe(1);
    expect(s?.boolean).toBe(true);
    expect(s?.quality).toBe('GOOD');
  });

  it('returns null when there is no numeric or boolean value', () => {
    expect(extractSample({ unit: 'bar' }, '2026-09-05T17:20:00.000Z')).toBeNull();
  });
});

describe('isBooleanPayload', () => {
  it('detects boolean value or type BOOLEAN', () => {
    expect(isBooleanPayload(true)).toBe(true);
    expect(isBooleanPayload({ value: false })).toBe(true);
    expect(isBooleanPayload({ value: 1, type: 'BOOLEAN' })).toBe(true);
    expect(isBooleanPayload({ value: 1.35 })).toBe(false);
  });
});

describe('mergeSeries', () => {
  it('appends live after historian and drops points outside the window', () => {
    const from = Date.parse('2026-09-05T17:00:00.000Z');
    const to = Date.parse('2026-09-05T18:00:00.000Z');
    const historian = [
      extractSample(1, '2026-09-05T16:59:00.000Z')!,
      extractSample(2, '2026-09-05T17:10:00.000Z')!,
    ];
    const live = [extractSample(3, '2026-09-05T17:50:00.000Z')!];
    const merged = mergeSeries(historian, live, from, to);
    expect(merged.map((s) => s.v)).toEqual([2, 3]);
  });
});

describe('numericTableRows', () => {
  it('returns newest first and caps at 200', () => {
    const samples = Array.from({ length: 210 }, (_, i) =>
      extractSample(i, new Date(Date.parse('2026-09-05T17:00:00.000Z') + i * 1000).toISOString())!,
    );
    const rows = numericTableRows(samples);
    expect(rows).toHaveLength(200);
    expect(rows[0].v).toBe(209);
  });
});

describe('booleanTransitions', () => {
  it('lists 0→1 and 1→0 only', () => {
    const samples = [
      extractSample({ value: false }, '2026-09-05T17:00:00.000Z')!,
      extractSample({ value: false }, '2026-09-05T17:01:00.000Z')!,
      extractSample({ value: true }, '2026-09-05T17:02:00.000Z')!,
      extractSample({ value: true }, '2026-09-05T17:03:00.000Z')!,
      extractSample({ value: false }, '2026-09-05T17:04:00.000Z')!,
    ];
    const rows = booleanTransitions(samples);
    expect(rows).toEqual([
      { t: Date.parse('2026-09-05T17:04:00.000Z'), from: 1, to: 0 },
      { t: Date.parse('2026-09-05T17:02:00.000Z'), from: 0, to: 1 },
    ]);
  });
});

describe('downsample', () => {
  it('does not change series at or under 1500 points', () => {
    const samples = Array.from({ length: 10 }, (_, i) =>
      extractSample(i, new Date(1_000_000 + i * 1000).toISOString())!,
    );
    expect(downsample(samples)).toHaveLength(10);
  });

  it('caps a long series at 1500 using min/max buckets', () => {
    const samples = Array.from({ length: 4000 }, (_, i) =>
      extractSample(i, new Date(1_000_000 + i * 1000).toISOString())!,
    );
    expect(downsample(samples).length).toBeLessThanOrEqual(1500);
    expect(downsample(samples).length).toBeGreaterThan(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/lib/condition-monitoring/series.test.ts`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./series`

- [ ] **Step 3: Write minimal implementation**

```ts
export type Sample = {
  t: number;
  v: number;
  quality: string | null;
  boolean: boolean;
};

function asBooleanFlag(payload: unknown): boolean {
  if (typeof payload === 'boolean') return true;
  if (payload && typeof payload === 'object') {
    const rec = payload as Record<string, unknown>;
    if (typeof rec.value === 'boolean') return true;
    const type = String(rec.type ?? rec.Type ?? '').toUpperCase();
    if (type === 'BOOLEAN') return true;
  }
  return false;
}

export function isBooleanPayload(payload: unknown): boolean {
  return asBooleanFlag(payload);
}

function rawValue(payload: unknown): unknown {
  if (payload && typeof payload === 'object' && 'value' in payload) {
    return (payload as { value: unknown }).value;
  }
  return payload;
}

export function extractSample(payload: unknown, timestamp: string): Sample | null {
  const raw = rawValue(payload);
  const boolean = asBooleanFlag(payload) || typeof raw === 'boolean';
  let v: number | null = null;
  if (typeof raw === 'boolean') v = raw ? 1 : 0;
  else if (typeof raw === 'number' && Number.isFinite(raw)) v = raw;
  else if (raw === 'true' || raw === 'false') v = raw === 'true' ? 1 : 0;
  if (v === null) return null;
  const rec = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const qualityRaw = rec.quality ?? rec.Quality;
  const quality = typeof qualityRaw === 'string' && qualityRaw.trim() ? qualityRaw : null;
  const t = Date.parse(timestamp);
  if (!Number.isFinite(t)) return null;
  return { t, v, quality, boolean };
}

export function mergeSeries(
  historian: Sample[],
  live: Sample[],
  fromMs: number,
  toMs: number,
): Sample[] {
  const inWindow = (s: Sample) => s.t >= fromMs && s.t <= toMs;
  const merged = [...historian.filter(inWindow), ...live.filter(inWindow)];
  merged.sort((a, b) => a.t - b.t);
  return merged;
}

export function numericTableRows(samples: Sample[], cap = 200): Sample[] {
  return [...samples].sort((a, b) => b.t - a.t).slice(0, cap);
}

export function booleanTransitions(
  samples: Sample[],
  cap = 200,
): { t: number; from: number; to: number }[] {
  const ordered = [...samples].sort((a, b) => a.t - b.t);
  const rows: { t: number; from: number; to: number }[] = [];
  for (let i = 1; i < ordered.length; i += 1) {
    const from = ordered[i - 1].v ? 1 : 0;
    const to = ordered[i].v ? 1 : 0;
    if (from !== to) rows.push({ t: ordered[i].t, from, to });
  }
  return rows.reverse().slice(0, cap);
}

export function downsample(samples: Sample[], maxPoints = 1500): Sample[] {
  if (samples.length <= maxPoints) return samples;
  const bucketCount = Math.floor(maxPoints / 2);
  const ordered = [...samples].sort((a, b) => a.t - b.t);
  const start = ordered[0].t;
  const span = Math.max(1, ordered[ordered.length - 1].t - start);
  const buckets: Sample[][] = Array.from({ length: bucketCount }, () => []);
  for (const s of ordered) {
    const index = Math.min(bucketCount - 1, Math.floor(((s.t - start) / span) * bucketCount));
    buckets[index].push(s);
  }
  const out: Sample[] = [];
  for (const bucket of buckets) {
    if (bucket.length === 0) continue;
    const min = bucket.reduce((a, b) => (a.v <= b.v ? a : b));
    const max = bucket.reduce((a, b) => (a.v >= b.v ? a : b));
    if (min.t <= max.t) out.push(min, max);
    else out.push(max, min);
  }
  return out.slice(0, maxPoints);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/lib/condition-monitoring/series.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/condition-monitoring/series.ts 11_frontend/src/lib/condition-monitoring/series.test.ts
git commit -m "feat(condition-monitoring): merge historian and live samples with boolean transitions"
```

---

### Task 3: KPI counts

**Files:**
- Create: `11_frontend/src/lib/condition-monitoring/kpis.ts`
- Test: `11_frontend/src/lib/condition-monitoring/kpis.test.ts`

**Interfaces:**
- Consumes: `GraphqlConnectivityTag`; `Sample` from `./series`; `ActiveAlarm` from `11_frontend/src/types/alarm.ts`; `tagMatchesNode` is **not** required — alarm topic uses the same prefix-or-leaf rule against the tag
- Produces:
  - `export type ConditionKpis = { inView: number; live: number; faultsOn: number; unacked: number; critical: number }`
  - `alarmMatchesTag(alarmTopic: string, tag: GraphqlConnectivityTag): boolean`
  - `conditionKpis(args: { tags: GraphqlConnectivityTag[]; latestByTopic: Record<string, Sample | undefined>; liveTopics: Set<string>; alarms: ActiveAlarm[] }): ConditionKpis`

A fault tag is one whose `displayName` or last `mqttTopic` segment is `Fault` (case-insensitive) and whose latest value is 1/true.

Unacked = `status === 'ACTIVE_UNACK' || status === 'CLEARED_UNACK'`. Critical = those with `severity === 'CRITICAL'`.

- [ ] **Step 1: Write the failing test**

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/lib/condition-monitoring/kpis.test.ts`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./kpis`

- [ ] **Step 3: Write minimal implementation**

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/lib/condition-monitoring/kpis.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/condition-monitoring/kpis.ts 11_frontend/src/lib/condition-monitoring/kpis.test.ts
git commit -m "feat(condition-monitoring): derive in-view, live, fault and alarm KPI counts"
```

---

### Task 4: Time range presets

**Files:**
- Create: `11_frontend/src/lib/condition-monitoring/time-range.ts`
- Test: `11_frontend/src/lib/condition-monitoring/time-range.test.ts`

**Interfaces:**
- Produces:
  - `export const TIME_RANGE_PRESETS = ['15m', '60m', '4h', '24h'] as const`
  - `export type TimeRangePreset = (typeof TIME_RANGE_PRESETS)[number]`
  - `export const DEFAULT_TIME_RANGE: TimeRangePreset = '60m'`
  - `rangeWindow(preset: TimeRangePreset, nowMs: number): { fromIso: string; toIso: string; fromMs: number; toMs: number }`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import { DEFAULT_TIME_RANGE, rangeWindow } from './time-range';

describe('rangeWindow', () => {
  it('defaults to 60 minutes and computes 15m / 4h / 24h from nowMs', () => {
    expect(DEFAULT_TIME_RANGE).toBe('60m');
    const now = Date.parse('2026-09-05T18:00:00.000Z');
    expect(rangeWindow('60m', now).fromIso).toBe('2026-09-05T17:00:00.000Z');
    expect(rangeWindow('15m', now).fromIso).toBe('2026-09-05T17:45:00.000Z');
    expect(rangeWindow('4h', now).fromIso).toBe('2026-09-05T14:00:00.000Z');
    expect(rangeWindow('24h', now).fromIso).toBe('2026-09-04T18:00:00.000Z');
    expect(rangeWindow('60m', now).toIso).toBe('2026-09-05T18:00:00.000Z');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/lib/condition-monitoring/time-range.test.ts`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./time-range`

- [ ] **Step 3: Write minimal implementation**

```ts
export const TIME_RANGE_PRESETS = ['15m', '60m', '4h', '24h'] as const;
export type TimeRangePreset = (typeof TIME_RANGE_PRESETS)[number];
export const DEFAULT_TIME_RANGE: TimeRangePreset = '60m';

const MS: Record<TimeRangePreset, number> = {
  '15m': 15 * 60 * 1000,
  '60m': 60 * 60 * 1000,
  '4h': 4 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
};

export function rangeWindow(
  preset: TimeRangePreset,
  nowMs: number,
): { fromIso: string; toIso: string; fromMs: number; toMs: number } {
  const fromMs = nowMs - MS[preset];
  return {
    fromMs,
    toMs: nowMs,
    fromIso: new Date(fromMs).toISOString(),
    toIso: new Date(nowMs).toISOString(),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/lib/condition-monitoring/time-range.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/condition-monitoring/time-range.ts 11_frontend/src/lib/condition-monitoring/time-range.test.ts
git commit -m "feat(condition-monitoring): add 15m 60m 4h 24h lookback windows"
```

---

### Task 5: SVG chart path (line and step)

**Files:**
- Create: `11_frontend/src/components/condition-monitoring/SignalChart.tsx`
- Test: `11_frontend/src/components/condition-monitoring/SignalChart.test.tsx`

**Interfaces:**
- Consumes: `Sample`, `downsample` from `../../lib/condition-monitoring/series`
- Produces:
  - `chartPath(samples: Sample[], width: number, height: number, mode: 'line' | 'step'): string`
  - `SignalChart` — SVG; empty copy `No historian points in range` when `samples.length === 0`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { chartPath, SignalChart } from './SignalChart';
import type { Sample } from '../../lib/condition-monitoring/series';

const s = (t: number, v: number): Sample => ({ t, v, quality: null, boolean: false });

describe('chartPath', () => {
  it('draws a continuous polyline for line mode', () => {
    const d = chartPath([s(0, 0), s(10, 10)], 100, 40, 'line');
    expect(d.startsWith('M')).toBe(true);
    expect(d.includes('H')).toBe(false);
  });

  it('holds the last Y then steps for boolean mode', () => {
    const d = chartPath([s(0, 0), s(10, 1)], 100, 40, 'step');
    expect(d.includes('H') || /L[\d.]+,[\d.]+ L/.test(d)).toBe(true);
  });
});

describe('SignalChart', () => {
  it('shows the empty historian copy when there are no samples', () => {
    render(<SignalChart samples={[]} mode="line" />);
    expect(screen.getByText(/no historian points in range/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/components/condition-monitoring/SignalChart.test.tsx`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./SignalChart`

- [ ] **Step 3: Write minimal implementation**

```tsx
import React, { useMemo } from 'react';
import { downsample, type Sample } from '../../lib/condition-monitoring/series';

const WIDTH = 320;
const HEIGHT = 96;
const PAD = 4;

export function chartPath(
  samples: Sample[],
  width: number,
  height: number,
  mode: 'line' | 'step',
): string {
  if (samples.length === 0) return '';
  const xs = samples.map((s) => s.t);
  const ys = samples.map((s) => s.v);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const x = (t: number) => PAD + ((t - minX) / spanX) * (width - PAD * 2);
  const y = (v: number) => HEIGHT - PAD - ((v - minY) / spanY) * (height - PAD * 2);
  const pts = samples.map((s) => ({ x: x(s.t), y: y(s.v) }));
  if (mode === 'step') {
    let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for (let i = 1; i < pts.length; i += 1) {
      d += ` H${pts[i].x.toFixed(1)} V${pts[i].y.toFixed(1)}`;
    }
    return d;
  }
  return pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ');
}

export const SignalChart: React.FC<{
  samples: Sample[];
  mode: 'line' | 'step';
}> = ({ samples, mode }) => {
  const drawn = useMemo(() => downsample(samples), [samples]);
  if (drawn.length === 0) {
    return <p className="py-6 text-center text-xs text-zinc-500">No historian points in range</p>;
  }
  const d = chartPath(drawn, WIDTH, HEIGHT, mode);
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-24 w-full" role="img" aria-label="Signal trend">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-[#FF7A00]" />
    </svg>
  );
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/components/condition-monitoring/SignalChart.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/condition-monitoring/SignalChart.tsx 11_frontend/src/components/condition-monitoring/SignalChart.test.tsx
git commit -m "feat(condition-monitoring): draw SVG line and step charts from samples"
```

---

### Task 6: SignalCard Graph | Table

**Files:**
- Create: `11_frontend/src/components/condition-monitoring/SignalCard.tsx`
- Test: `11_frontend/src/components/condition-monitoring/SignalCard.test.tsx`

**Interfaces:**
- Consumes: `GraphqlConnectivityTag`; `Sample`; `numericTableRows`, `booleanTransitions` from series; `SignalChart`
- Produces: `SignalCard` props `{ tag: GraphqlConnectivityTag; samples: Sample[]; latest: Sample | undefined }`
- Default view Graph. Toggle **Graph** / **Table**. Boolean cards use step + transition table (`19:20:35  0 → 1`). Numeric cards use line + timestamp/value. Latest value on the header; quality `—` when `latest.quality` is null. No Unsubscribe.

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SignalCard } from './SignalCard';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import type { Sample } from '../../lib/condition-monitoring/series';

const TAG: GraphqlConnectivityTag = {
  serverId: 's1',
  nodeId: 'n1',
  browsePath: 'P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/P201/Fault',
  subscribed: true,
};

const samples: Sample[] = [
  { t: Date.parse('2026-09-05T17:00:00.000Z'), v: 0, quality: null, boolean: true },
  { t: Date.parse('2026-09-05T17:02:00.000Z'), v: 1, quality: 'GOOD', boolean: true },
];

describe('SignalCard', () => {
  it('shows name, topic, latest value, and Graph by default', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    expect(screen.getByText('Fault')).toBeTruthy();
    expect(screen.getByText('Server/OpcPlc/P201/Fault')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByRole('img', { name: /signal trend/i })).toBeTruthy();
    expect(screen.queryByText(/0 → 1/)).toBeNull();
  });

  it('switches to a boolean transition table', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={samples[1]} />);
    fireEvent.click(screen.getByRole('button', { name: /^table$/i }));
    expect(screen.getByText(/0 → 1/)).toBeTruthy();
    expect(screen.queryByRole('img', { name: /signal trend/i })).toBeNull();
  });

  it('renders — when quality is missing', () => {
    render(<SignalCard tag={TAG} samples={samples} latest={{ ...samples[1], quality: null }} />);
    expect(screen.getByText('—')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/components/condition-monitoring/SignalCard.test.tsx`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./SignalCard`

- [ ] **Step 3: Write minimal implementation**

```tsx
import React, { useMemo, useState } from 'react';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import {
  booleanTransitions,
  numericTableRows,
  type Sample,
} from '../../lib/condition-monitoring/series';
import { ConsoleCard } from '../ui/console-ui';
import { SignalChart } from './SignalChart';

function clock(t: number): string {
  return new Date(t).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export const SignalCard: React.FC<{
  tag: GraphqlConnectivityTag;
  samples: Sample[];
  latest: Sample | undefined;
}> = ({ tag, samples, latest }) => {
  const [mode, setMode] = useState<'graph' | 'table'>('graph');
  const isBoolean = samples.some((s) => s.boolean) || latest?.boolean === true;
  const transitions = useMemo(() => booleanTransitions(samples), [samples]);
  const rows = useMemo(() => numericTableRows(samples), [samples]);

  return (
    <ConsoleCard padding="sm" className="flex min-h-[11rem] flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{tag.displayName}</p>
          <p className="break-all font-mono text-[11px] text-zinc-500">{tag.mqttTopic}</p>
        </div>
        <div className="text-right">
          <p className="text-sm tabular-nums text-emerald-400">
            {latest ? (isBoolean ? String(latest.v) : String(latest.v)) : '—'}
          </p>
          <p className="text-[11px] text-zinc-500">{latest?.quality ?? '—'}</p>
        </div>
      </div>
      <div className="flex gap-1">
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'graph' ? 'bg-zinc-800 text-white' : 'text-zinc-500'}`}
          onClick={() => setMode('graph')}
        >
          Graph
        </button>
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'table' ? 'bg-zinc-800 text-white' : 'text-zinc-500'}`}
          onClick={() => setMode('table')}
        >
          Table
        </button>
      </div>
      {mode === 'graph' ? (
        <SignalChart samples={samples} mode={isBoolean ? 'step' : 'line'} />
      ) : isBoolean ? (
        <table className="w-full text-left text-[11px] text-zinc-300">
          <tbody>
            {transitions.map((row) => (
              <tr key={row.t}>
                <td className="py-0.5 tabular-nums text-zinc-500">{clock(row.t)}</td>
                <td>
                  {row.from} → {row.to}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="w-full text-left text-[11px] text-zinc-300">
          <tbody>
            {rows.map((row) => (
              <tr key={row.t}>
                <td className="py-0.5 tabular-nums text-zinc-500">{clock(row.t)}</td>
                <td className="tabular-nums">{row.v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ConsoleCard>
  );
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/components/condition-monitoring/SignalCard.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/condition-monitoring/SignalCard.tsx 11_frontend/src/components/condition-monitoring/SignalCard.test.tsx
git commit -m "feat(condition-monitoring): add Graph and Table signal cards"
```

---

### Task 7: Page shell — catalog, scope, search, empty states

**Files:**
- Create: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx`
- Test: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx`

**Interfaces:**
- Consumes: Tasks 1–6 helpers; `UnsTreeView`; `useUNS().selectedNode`; `useAuth().hasPermission('uns_tree')`; `unsGraphQLClient.getConnectivityServers`; console `PageShell`, `PageContent`, `FilterToolbar`, `CompactKpiRow`, `PageStat`
- Produces: `ConditionMonitoringView` that loads subscribed tags, scopes with `tagInScope` + `filterTagsBySearch`, shows empty/error copy from the spec. **Do not** call historian or MQTT in this task — cards render with `samples={[]}` so the historian empty copy appears. KPI chips can show `inView` only (others 0) until Task 8/10.

Mock `unsGraphQLClient` the same way as `ConnectivityView.test.tsx`. Mock `useUNS` with a controllable `selectedNode`. Mock `useAlarms` with `{ activeAlarms: [] }`. Mock `useAuth` with `hasPermission: (f) => f === 'uns_tree'`.

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const getConnectivityServers = vi.hoisted(() => vi.fn());
const getHistoricEvents = vi.hoisted(() => vi.fn());
const subscribeMqttMessages = vi.hoisted(() => vi.fn());

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getConnectivityServers, getHistoricEvents, subscribeMqttMessages },
}));

const uns = vi.hoisted(() => ({
  selectedNode: null as null | { topic: string; name: string; lastUpdated: string; isLeaf: boolean; children?: unknown[] },
}));
vi.mock('../../context/UNSContext', () => ({ useUNS: () => uns }));
vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ activeAlarms: [] }),
}));
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    hasPermission: (feature: string) => feature === 'uns_tree',
  }),
}));
vi.mock('../home/UnsTreeView', () => ({
  UnsTreeView: () => <div>Namespace Tree</div>,
}));

import { ConditionMonitoringView } from './ConditionMonitoringView';

const FAULT = {
  serverId: 's1',
  nodeId: 'n1',
  browsePath: 'Distribution/P201/Fault',
  displayName: 'Fault',
  mqttTopic: 'Server/OpcPlc/Distribution/P201/Fault',
  subscribed: true,
};
const SPEED = {
  serverId: 's1',
  nodeId: 'n2',
  browsePath: 'Distribution/P202/Speed',
  displayName: 'Speed',
  mqttTopic: 'Server/OpcPlc/Distribution/P202/Speed',
  subscribed: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  uns.selectedNode = null;
  getConnectivityServers.mockResolvedValue([
    { id: 's1', name: 'wtp', protocol: 'OPC_UA', endpoint: 'opc.tcp://x', lastStatus: 'connected', lastError: '', tags: [FAULT, SPEED, { ...FAULT, nodeId: 'n3', subscribed: false, displayName: 'Ignored' }] },
  ]);
  getHistoricEvents.mockResolvedValue([]);
  subscribeMqttMessages.mockReturnValue(() => undefined);
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ConditionMonitoringView />
    </MemoryRouter>,
  );
}

describe('ConditionMonitoringView catalog', () => {
  it('shows AccessRestricted when uns_tree is denied', async () => {
    const auth = await import('../../context/AuthContext');
    vi.spyOn(auth, 'useAuth').mockReturnValue({
      hasPermission: () => false,
    } as never);
    renderPage();
    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getConnectivityServers).not.toHaveBeenCalled();
  });

  it('shows a catalog error without the empty-subscribe copy', async () => {
    getConnectivityServers.mockRejectedValue(new Error('column missing'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/column missing/i)).toBeTruthy());
    expect(screen.queryByText(/subscribe tags in assets/i)).toBeNull();
  });

  it('shows the subscribe empty state when the catalog has no subscribed tags', async () => {
    getConnectivityServers.mockResolvedValue([
      { id: 's1', name: 'wtp', protocol: 'OPC_UA', endpoint: 'x', lastStatus: 'untested', lastError: '', tags: [] },
    ]);
    renderPage();
    await waitFor(() => expect(screen.getByText(/subscribe tags in assets & connectivity/i)).toBeTruthy());
    expect(screen.getByRole('link', { name: /assets & connectivity/i })).toHaveAttribute('href', '/connectivity');
  });

  it('renders one card per subscribed tag and hides All signals until scoped', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    expect(screen.getByText('Speed')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /all signals/i })).toBeNull();
  });

  it('scopes to a loaded P201 node and All signals restores both cards', async () => {
    uns.selectedNode = {
      topic: 'AcmeWater/Site1/Distribution/Train1/P201',
      name: 'P201',
      lastUpdated: '',
      isLeaf: true,
      children: [],
    };
    const { rerender } = renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    expect(screen.queryByText('Speed')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /all signals/i }));
    rerender(
      <MemoryRouter>
        <ConditionMonitoringView />
      </MemoryRouter>,
    );
    // After click, scope is null even if selectedNode remains
    await waitFor(() => expect(screen.getByText('Speed')).toBeTruthy());
  });
});
```

The access-denied test above is brittle if `useAuth` is already mocked. Prefer the ConnectivityView pattern: a hoisted `auth.hasPermission` you can flip in the test. Use that pattern in the real file (copy `ConnectivityView.test.tsx` access test).

**Access test (use this instead of the spy):**

```ts
const auth = vi.hoisted(() => ({
  hasPermission: (feature: string) => feature === 'uns_tree',
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));
```

In the denied test: `auth.hasPermission = () => false`.

**Scope test:** keep `scoped` in component state. On `selectedNode` change, set `scoped = true` when `selectedNode` is non-null. **All signals** sets `scoped = false`. `tagInScope(tag, scoped ? selectedNode : null)`.

For the Link href: `HashRouter` uses `#/connectivity`. Use `<Link to="/connectivity">` so the accessible name works; in MemoryRouter `href` is `/connectivity`.

If the All-signals scope test is awkward with rerender, drive it in one render: start with `uns.selectedNode` set, assert Speed hidden, click All signals, assert Speed visible **without** rerender (state lives in the view).

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Working directory: `11_frontend`  
Expected: FAIL — cannot resolve `./ConditionMonitoringView`

- [ ] **Step 3: Write minimal implementation**

Implement `ConditionMonitoringView` as:

```tsx
// Sketch — keep this structure; fill JSX with console primitives.
export const ConditionMonitoringView: React.FC = () => {
  const { hasPermission } = useAuth();
  const { selectedNode } = useUNS();
  const [servers, setServers] = useState<GraphqlConnectivityServer[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scoped, setScoped] = useState(false);
  const [search, setSearch] = useState('');
  const [preset, setPreset] = useState<TimeRangePreset>(DEFAULT_TIME_RANGE);

  useEffect(() => {
    if (selectedNode) setScoped(true);
  }, [selectedNode]);

  useEffect(() => {
    if (!hasPermission('uns_tree')) return;
    void (async () => {
      try {
        setLoadError(null);
        const list = await unsGraphQLClient.getConnectivityServers('OPC_UA');
        setServers(list);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : 'Connectivity catalog could not be loaded.');
        setServers([]);
      }
    })();
  }, [hasPermission]);

  const subscribed = servers.flatMap((s) => s.tags.filter((t) => t.subscribed));
  const scopedTags = subscribed.filter((t) => tagInScope(t, scoped ? selectedNode : null));
  const visible = filterTagsBySearch(scopedTags, search);

  if (!hasPermission('uns_tree')) {
    return (
      <PageShell scroll={false}>
        <AccessRestricted featureKey="uns_tree" />
      </PageShell>
    );
  }

  return (
    <PageShell id="condition-monitoring-view" scroll={false} className="flex flex-col">
      <div className="flex min-h-0 flex-1">
        <section className="hidden w-[280px] shrink-0 overflow-hidden border-r border-zinc-800 md:block">
          <UnsTreeView />
        </section>
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <PageContent fullWidth>
            {loadError ? <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{loadError}</div> : null}
            <FilterToolbar
              search={{ value: search, onChange: setSearch, placeholder: 'Search name or topic…' }}
              selects={[{
                value: preset,
                onChange: (v) => setPreset(v as TimeRangePreset),
                'aria-label': 'Time range',
                options: [
                  { value: '15m', label: 'Last 15 minutes' },
                  { value: '60m', label: 'Last 60 minutes' },
                  { value: '4h', label: 'Last 4 hours' },
                  { value: '24h', label: 'Last 24 hours' },
                ],
              }]}
              trailing={scoped ? <BtnGhost type="button" onClick={() => setScoped(false)}>All signals</BtnGhost> : null}
            />
            {/* cards or empty states from spec §9 */}
          </PageContent>
        </div>
      </div>
    </PageShell>
  );
};
```

Empty copy (exact):

- No loadError, `subscribed.length === 0`: `Subscribe tags in Assets & Connectivity.` with `<Link to="/connectivity">Assets & Connectivity</Link>`
- `scoped && visible.length === 0 && subscribed.length > 0 && !search`: `No subscribed signals in this zone.`
- `search && visible.length === 0`: `No signals match this search.`

Grid: `div` `className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"` of `SignalCard` with `samples={[]}` `latest={undefined}`.

On small screens still show the tree above the grid (`md:hidden` block + `md:block` rail) so the left tree is not desktop-only forgotten — match HomeView: tree is a column on md+, a top pane on mobile (`h-[300px]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Expected: PASS

If the access test fights the hoisted mock, follow `ConnectivityView.test.tsx` exactly (flip `auth.hasPermission` in `beforeEach` reset).

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx
git commit -m "feat(condition-monitoring): load subscribed tags and scope the card grid"
```

---

### Task 8: Historian lookback + live tail

**Files:**
- Modify: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx`
- Modify: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx`

**Interfaces:**
- Consumes: `getHistoricEvents(topic, fromIso, toIso)`, `subscribeMqttMessages(topics, onMessage)`, `rangeWindow`, `extractSample`, `mergeSeries`
- Produces: per-topic `samples` passed into `SignalCard`. Live topics go into a `Set` for Task 10. Changing `preset` refetches historian and drops out-of-window live points. Subscription topics = **visible** tags’ `mqttTopic`s. Unsubscribe on unmount or when the visible topic set changes. Independent of `UNSContext` feed pause.

`getHistoricEvents` already throws on `res.error` — catch per batch: set `historianError` banner, keep cards.

- [ ] **Step 1: Extend the failing tests** (add to the existing test file)

```tsx
  it('loads historian points for visible topics and appends live MQTT samples', async () => {
    getHistoricEvents.mockImplementation(async (topic: string) => {
      if (topic.endsWith('Fault')) {
        return [{
          id: 'h1',
          topic,
          timestamp: '2026-09-05T17:10:00.000Z',
          payload: { value: false },
        }];
      }
      return [];
    });
    let onMsg: ((msg: { topic: string; payload: unknown; timestamp: string; id: string }) => void) | undefined;
    subscribeMqttMessages.mockImplementation((topics: string[], cb: typeof onMsg) => {
      onMsg = cb;
      return () => undefined;
    });
    renderPage();
    await waitFor(() => expect(getHistoricEvents).toHaveBeenCalled());
    expect(getHistoricEvents.mock.calls.map((c) => c[0]).sort()).toEqual([
      'Server/OpcPlc/Distribution/P201/Fault',
      'Server/OpcPlc/Distribution/P202/Speed',
    ]);
    await waitFor(() => expect(subscribeMqttMessages).toHaveBeenCalled());
    onMsg?.({
      id: 'm1',
      topic: 'Server/OpcPlc/Distribution/P201/Fault',
      payload: { value: true },
      timestamp: new Date().toISOString(),
    });
    fireEvent.click(screen.getAllByRole('button', { name: /^table$/i })[0]);
    await waitFor(() => expect(screen.getByText(/0 → 1/)).toBeTruthy());
  });

  it('shows a historian banner when getHistoricEvents throws and keeps cards', async () => {
    getHistoricEvents.mockRejectedValue(new Error('historian down'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/historian down/i)).toBeTruthy());
    expect(screen.getByText('Fault')).toBeTruthy();
  });
```

`getHistoricEvents` must be called with `(topic, fromIso, toIso)`.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `npm run test:run -- src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Expected: FAIL on historian/live assertions

- [ ] **Step 3: Wire lookback and tail**

In the view:

```tsx
const window = rangeWindow(preset, Date.now());
const [historianByTopic, setHistorianByTopic] = useState<Record<string, Sample[]>>({});
const [liveByTopic, setLiveByTopic] = useState<Record<string, Sample[]>>({});
const [liveTopics, setLiveTopics] = useState<Set<string>>(() => new Set());
const [historianError, setHistorianError] = useState<string | null>(null);

useEffect(() => {
  const topics = visible.map((t) => t.mqttTopic);
  let cancelled = false;
  setHistorianError(null);
  void Promise.all(
    topics.map(async (topic) => {
      const events = await unsGraphQLClient.getHistoricEvents(topic, window.fromIso, window.toIso);
      return [
        topic,
        events
          .map((e) => extractSample(e.payload, e.timestamp))
          .filter((s): s is Sample => s !== null),
      ] as const;
    }),
  )
    .then((entries) => {
      if (cancelled) return;
      setHistorianByTopic(Object.fromEntries(entries));
      setLiveByTopic({});
    })
    .catch((err: unknown) => {
      if (!cancelled) {
        setHistorianError(err instanceof Error ? err.message : 'Historian query failed.');
      }
    });
  return () => {
    cancelled = true;
  };
}, [preset, visible.map((t) => t.mqttTopic).join('|')]);

useEffect(() => {
  const topics = visible.map((t) => t.mqttTopic);
  if (topics.length === 0) return undefined;
  return unsGraphQLClient.subscribeMqttMessages(topics, (msg) => {
    const sample = extractSample(msg.payload, msg.timestamp);
    if (!sample) return;
    setLiveTopics((prev) => new Set(prev).add(msg.topic));
    setLiveByTopic((prev) => ({
      ...prev,
      [msg.topic]: [...(prev[msg.topic] ?? []), sample],
    }));
  });
}, [visible.map((t) => t.mqttTopic).join('|')]);
```

Per card:

```tsx
const samples = mergeSeries(
  historianByTopic[tag.mqttTopic] ?? [],
  liveByTopic[tag.mqttTopic] ?? [],
  window.fromMs,
  Date.now(),
);
const latest = samples[samples.length - 1];
```

Recompute `window` at render for the merge upper bound so live points after mount still sit in range (`toMs` = `Date.now()`). Historian fetch uses the preset window at effect time.

Show `historianError` in a second rose banner under the catalog banner.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test:run -- src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx
git commit -m "feat(condition-monitoring): load historian lookback and append live MQTT samples"
```

---

### Task 9: Route, sidebar, header

**Files:**
- Modify: `11_frontend/src/App.tsx` — add route; redirect `/tree`
- Modify: `11_frontend/src/components/layout/Sidebar.tsx` — `MAIN_MENU` item `UNS Tree` → `{ to: '/condition-monitoring', tabId: 'home', label: 'Condition Monitoring', icon: Activity, featureKey: 'uns_tree' }` (keep `Layers` if you prefer; `Activity` is already imported for System Health — use `Gauge` from lucide-react if you add the import, or keep `Layers`)
- Modify: `11_frontend/src/components/common/Header.tsx` — `getPageHeading`: `/condition-monitoring` and `/tree` return `{ title: 'Condition Monitoring' }` (no greeting subtitle)
- Test: `11_frontend/src/App.redirect.test.tsx`

`AuthContext` `TAB_FEATURES.home` stays `{ feature: 'uns_tree', name: 'Plant' }`. Sidebar `tabId` stays `home`.

`isActive` for the new path: `location.pathname === '/condition-monitoring' || location.pathname.startsWith('/condition-monitoring/')`. The existing `/tree` branch can stay for the redirect frame.

- [ ] **Step 1: Write the failing test**

```tsx
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

describe('condition monitoring routes', () => {
  it('redirects /tree to /condition-monitoring', () => {
    render(
      <MemoryRouter initialEntries={['/tree']}>
        <Routes>
          <Route path="/condition-monitoring" element={<div>CM_PAGE</div>} />
          <Route path="/tree" element={<Navigate to="/condition-monitoring" replace />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('CM_PAGE')).toBeTruthy();
  });

  it('wires the same redirect and view in App.tsx', () => {
    const src = readFileSync(resolve(__dirname, './App.tsx'), 'utf8');
    expect(src).toMatch(/path="\/condition-monitoring"/);
    expect(src).toMatch(/ConditionMonitoringView/);
    expect(src).toMatch(/path="\/tree"/);
    expect(src).toMatch(/Navigate to="\/condition-monitoring"/);
  });

  it('renames the sidebar entry', () => {
    const src = readFileSync(resolve(__dirname, './components/layout/Sidebar.tsx'), 'utf8');
    expect(src).toMatch(/Condition Monitoring/);
    expect(src).toMatch(/\/condition-monitoring/);
    expect(src).not.toMatch(/label: 'UNS Tree'/);
  });

  it('uses a title-only header', () => {
    const src = readFileSync(resolve(__dirname, './components/common/Header.tsx'), 'utf8');
    expect(src).toMatch(/condition-monitoring/);
    expect(src).toMatch(/title: 'Condition Monitoring'/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/App.redirect.test.tsx`  
Working directory: `11_frontend`  
Expected: FAIL on App.tsx / Sidebar / Header assertions

- [ ] **Step 3: Apply the wiring**

`App.tsx` imports and routes (replace the `/tree` line):

```tsx
import { ConditionMonitoringView } from './components/condition-monitoring/ConditionMonitoringView';
```

```tsx
<Route path="/condition-monitoring" element={<ConditionMonitoringView />} />
<Route path="/tree" element={<Navigate to="/condition-monitoring" replace />} />
```

`Sidebar.tsx` `MAIN_MENU` second item:

```ts
{ to: '/condition-monitoring', tabId: 'home', label: 'Condition Monitoring', icon: Layers, featureKey: 'uns_tree' },
```

Update `isActive`:

```ts
if (item.to === '/condition-monitoring') {
  return location.pathname === '/condition-monitoring' || location.pathname.startsWith('/condition-monitoring/');
}
```

`Header.tsx` `getPageHeading` — replace the `/tree` block:

```ts
if (path.startsWith('/condition-monitoring') || path.startsWith('/tree')) {
  return { title: 'Condition Monitoring' };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test:run -- src/App.redirect.test.tsx src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/App.tsx 11_frontend/src/App.redirect.test.tsx 11_frontend/src/components/layout/Sidebar.tsx 11_frontend/src/components/common/Header.tsx
git commit -m "feat(condition-monitoring): replace #/tree with the Condition Monitoring route"
```

---

### Task 10: KPI row and alarm chips

**Files:**
- Modify: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx`
- Modify: `11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx`

**Interfaces:**
- Consumes: `conditionKpis`, `useAlarms().activeAlarms`, `useNavigate()`
- Produces: `CompactKpiRow` of five `PageStat compact` chips: In view, Live, Faults on, Unacked, Critical. Unacked and Critical are buttons (or clickable `PageStat` wrappers) that `navigate('/alerts')`.

- [ ] **Step 1: Add failing tests** to `ConditionMonitoringView.test.tsx`

Hoist alarms:

```ts
const alarms = vi.hoisted(() => ({ activeAlarms: [] as { topic: string; severity: string; status: string }[] }));
vi.mock('../../context/AlarmContext', () => ({ useAlarms: () => alarms }));
```

```tsx
  it('shows KPI counts for visible tags and goes to alerts on Unacked', async () => {
    alarms.activeAlarms = [
      {
        id: 'a1',
        ruleId: 'r',
        ruleName: 'f',
        topic: 'AcmeWater/Site1/P201/Fault',
        severity: 'CRITICAL',
        category: 'SAFETY',
        conditionDescription: '',
        currentValue: true,
        status: 'ACTIVE_UNACK',
        triggeredAt: '',
        targetRoles: ['engineer'],
      },
    ];
    renderPage();
    await waitFor(() => expect(screen.getByText('Fault')).toBeTruthy());
    expect(screen.getByText('In view').closest('div')?.textContent).toMatch(/2/);
    fireEvent.click(screen.getByRole('button', { name: /unacked/i }));
    // MemoryRouter: assert navigation via a mock navigate if you wrap with a spy.
  });
```

Use `createMemoryRouter` / `RouterProvider` if you need to assert `/alerts`. Or mock:

```ts
const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigate };
});
```

Then `expect(navigate).toHaveBeenCalledWith('/alerts')`.

Reset `alarms.activeAlarms = []` in `beforeEach`.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `npm run test:run -- src/components/condition-monitoring/ConditionMonitoringView.test.tsx`  
Expected: FAIL — no Unacked button / navigate

- [ ] **Step 3: Add the KPI row**

```tsx
const { activeAlarms } = useAlarms();
const navigate = useNavigate();
const latestByTopic = Object.fromEntries(
  visible.map((tag) => {
    const samples = mergeSeries(
      historianByTopic[tag.mqttTopic] ?? [],
      liveByTopic[tag.mqttTopic] ?? [],
      window.fromMs,
      Date.now(),
    );
    return [tag.mqttTopic, samples[samples.length - 1]];
  }),
);
const kpis = conditionKpis({
  tags: visible,
  latestByTopic,
  liveTopics,
  alarms: activeAlarms,
});

<CompactKpiRow>
  <PageStat compact label="In view" value={kpis.inView} icon={<Layers className="size-3.5" />} />
  <PageStat compact label="Live" value={kpis.live} icon={<Activity className="size-3.5" />} />
  <PageStat compact label="Faults on" value={kpis.faultsOn} icon={<AlertTriangle className="size-3.5" />} />
  <button type="button" aria-label="Unacked" onClick={() => navigate('/alerts')}>
    <PageStat compact label="Unacked" value={kpis.unacked} icon={<Bell className="size-3.5" />} />
  </button>
  <button type="button" aria-label="Critical" onClick={() => navigate('/alerts')}>
    <PageStat compact label="Critical" value={kpis.critical} icon={<AlertTriangle className="size-3.5" />} />
  </button>
</CompactKpiRow>
```

Do not acknowledge alarms here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test:run -- src/components/condition-monitoring/`  
Expected: PASS

Also run: `npm run test:run -- src/lib/condition-monitoring/ src/App.redirect.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.tsx 11_frontend/src/components/condition-monitoring/ConditionMonitoringView.test.tsx
git commit -m "feat(condition-monitoring): add compact KPI chips and alert navigation"
```

---

## Self-review (spec coverage)

| Spec section | Task |
| --- | --- |
| §3 IA, `#/tree` redirect, sidebar, header | 9 |
| §4 layout, FilterToolbar, time range, search, All signals | 4, 7 |
| §5 card set, name match, loaded descendants | 1, 7 |
| §6 card Graph \| Table, step, caps | 2, 5, 6 |
| §7 historian + dedicated live tail, errors | 8 |
| §8 KPI chips + `#/alerts` | 3, 10 |
| §9 empty states | 7 |
| §10 tests listed | 1, 2, 7, 8, 9 |
| §11 out of scope | Global Constraints; no Grafana/Live Feed mount |
| `uns_tree` + catalog forbidden ≠ empty plant | 7 |

No TBD/TODO placeholders. Helper signatures in later tasks match Tasks 1–4.
