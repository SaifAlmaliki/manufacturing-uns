# Operations Console Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `11_frontend` into an eleven-destination operations console where every screen is reachable from plant vocabulary, every claim on screen is derived from a real response, and the OEE, Asset Model and downtime capabilities that already exist in the platform have a UI.

**Architecture:** The router gains five destinations and three redirects. A grouped nav rail replaces the badge-laden sidebar. PLANT becomes a six-tab workspace over a selected Asset, driven by the client reads added in the foundation plan. Every fabricated string in the shell is deleted rather than reworded, and the sub-11px type is raised to the spec's scale. This plan consumes the client methods the foundation plan produced; where it needs one more read it reuses an existing document (Task 9) and says so, and it never adds a field that is not already in `07_uns_graphql`'s schema.

**Tech Stack:** React 19, TypeScript 5.8, Vite 6, Tailwind 4, react-router 7 (`HashRouter`), Recharts 3, Vitest 3 + Testing Library, Grafana embeds via `<iframe>`.

**Spec:** `docs/superpowers/specs/2026-09-02-operations-console-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-02-console-foundation.md` — every task from that plan must be complete and committed before Task 1 here. This plan calls `unsGraphQLClient.getAssets`, `getAsset`, `getAssetChildren`, `getUnmodelledTopics`, `getAssetModelSummary`, `getAlertRule`, `getAlertRuleSummary`, `getAlertRules`, `getOeeShiftResults`, `getDowntimeEvents`, `getDowntimePareto`, `getDowntimeReasons`, `assignDowntimeReason`, the types in `src/types/oee.ts`, the helpers in `src/lib/oee/format.ts`, `connectionState()` in `src/lib/health/connection-state.ts`, the narrowed `SystemHealthInfo`, and the Vitest tooling. None of it is redefined here.

## Global Constraints

- **Do not invent GraphQL fields.** Every read goes through a method that already exists on `unsGraphQLClient` after the foundation plan. If a screen needs data with no API, render an empty state that says so and label it **requires backend** in a code comment.
- **Browser talks to GraphQL only** — `POST /graphql`, `WS /graphql` — except `/simulator`, which talks to the simulator control API through nginx (ADR-0007). The browser never opens MQTT, Neo4j, Timescale, Kafka or Sparkplug protobuf.
- **No Sparkplug decoding in the browser.** Live Sparkplug is a badge over `BytesPayload`. Decoded values come only from `getSpbNodesByMetric`.
- **Tree queries never use `#`.** Roots are `+`. Children of node `N` are `{N.namespace}/+`. `spBv1.0/` never enters the ISA-95 tree. (The `#` at `src/context/UNSContext.tsx:172` and `:352` is the live MQTT feed subscription filter, not a tree query — leave it alone.)
- **Search never filters the left tree.** Matches are a separate list; clicking one expands the ancestors of the match.
- **No invented KPIs.** Availability, Performance, Quality and OEE come from `oeeShiftResults` and nothing else. There is no synthesised uptime, no derived target, no plant-wide roll-up.
- **Null is not zero.** A null ratio renders `—` via `formatRatio` from `src/lib/oee/format.ts`. `0%` must never appear for missing data (ADR-0008).
- **CONTEXT.md vocabulary, exactly:** Unified Namespace, UNS Node, Historic Event, Mapper, Metric, Asset, Asset Model, Enrichment, Unmodelled Topic, Process Visualization, Platform Observability, Alert Rule. "Alarm" is the event; "Alert Rule" is the configuration.
- **English only.** No i18n, no locale files, no mobile-first rewrite. Desktop-first at 1280px and up; the existing mobile drawer keeps working but is not a design target.
- **One frontend.** No second app, no UI served from FastAPI, no SSR.
- **Type scale:** 13px body, 12px dense tables and feeds, 11px labels and chrome. Nothing below 11px. `text-[8px]` and `text-[9px]` must not survive in `src/`.
- **Full viewport height, panes scroll, the shell does not.** Monospace for topics, metric names and JSON; sans for chrome.
- **Every behaviour added gets a Vitest test with the transport mocked at the `client.ts` boundary.** No live broker, no live GraphQL, no network in tests — `src/test/setup.ts` throws on unstubbed `fetch`/`WebSocket`.

---

## File Structure

```
11_frontend/src/
  App.tsx                                  MODIFY  eleven routes + three redirects
  components/
    layout/
      AppLayout.tsx                        MODIFY  truthful footer, new tab-id map
      Sidebar.tsx                          MODIFY  four grouped sections, no fabricated state
    common/
      ConnectionChip.tsx                   MODIFY  rebuilt on connectionState()
      EmptyState.tsx                       CREATE  instructional empty state
      StatusPill.tsx                       CREATE  Live/Degraded/Down/Connecting pill
      ValueWithUnit.tsx                    CREATE  value + Unit of Measure, null-safe
      DataTable.tsx                        CREATE  dense table shell with sticky header
      GrafanaEmbed.tsx                     MODIFY  variables + a real failure state
    plant/
      PlantView.tsx                        CREATE  asset canvas shell + six tabs
      AssetTreeRail.tsx                    CREATE  authored Asset tree, selection
      tabs/LiveTab.tsx                     CREATE
      tabs/TrendTab.tsx                    CREATE
      tabs/ShiftOeeTab.tsx                 CREATE
      tabs/StopsTab.tsx                    CREATE
      tabs/AlarmsTab.tsx                   CREATE
      tabs/ModelTab.tsx                    CREATE
    shift/
      ShiftView.tsx                        CREATE  standalone /shift destination
      ShiftResultTable.tsx                 CREATE
      DowntimePareto.tsx                   CREATE
      StopList.tsx                         CREATE
      ReassignReasonDialog.tsx             CREATE
    assets/
      AssetsView.tsx                       CREATE
      ModelSummaryHeader.tsx               CREATE
      UnmodelledTopicsList.tsx             CREATE
    namespace/
      NamespaceView.tsx                    CREATE  wraps the existing home/ components
      FindByProperty.tsx                   CREATE  getUnsNodesByProperty, moved out of explore/
    historian/
      HistorianView.tsx                    CREATE  three modes, no per-keystroke query
      HistorianQueryForm.tsx               CREATE  the form for all three modes
      HistorianTable.tsx                   MOVE    from explore/, four untruths removed
      HistorianTrendChart.tsx              MOVE    from explore/, unchanged
    health/
      HealthView.tsx                       CREATE  four panels + the dashboard switcher
      TransportPanel.tsx                   CREATE  the two transports, URLs, last-seen ages
      ReadSurfacePanel.tsx                 CREATE  Asset Model + Alert Rule counts
      NotObservablePanel.tsx               CREATE  the four stores a browser cannot reach
      HealthRow.tsx                        CREATE  one label/value line, used by both panels
    alarms/
      BrowserEvaluationNotice.tsx          CREATE  ADR-0005 stated, not concealed (Task 14)
      AlarmManagementView.tsx              MODIFY  three honest empty states + the notice
      AlarmAuditLog.tsx                    MODIFY  export through the shared CSV writer
      AlertRuleEditorModal.tsx             MODIFY  what this console does, split from what it
                                                   only records; the three hidden fields get
                                                   controls; no default plant (Task 24)
    home/                                  KEEP    UnsTreeView, LiveMqttFeed, PayloadInspector
      PayloadInspector.tsx                 MODIFY  Sparkplug decoding attributed correctly (Task 22)
    sparkplug/SparkplugView.tsx            MODIFY  invented byte size, seq and online dot out (Task 22)
    explore/ExploreView.tsx                DELETE  once HistorianView lands (Task 18)
    home/HomeView.tsx                      DELETE  once NamespaceView lands (Task 17)
    system/SystemHealthView.tsx            DELETE  once HealthView lands (Task 19)
    landing/LandingView.tsx                MODIFY  fabricated figures removed
    auth/LoginView.tsx                     MODIFY  fabricated claim removed
    users/UserManagementView.tsx           MODIFY  read-only, labelled not enforced (Task 21)
    users/CreateUserModal.tsx              DELETE  this console cannot create an account
    users/EditUserModal.tsx                DELETE  this console cannot grant a permission
  context/
    UNSContext.tsx                         MODIFY  NavigationTab, selectedAsset, jump targets;
                                                   live Sparkplug reaches the feed but still
                                                   never patches the tree (Task 22);
                                                   every feed message is evaluated (Task 23)
    AlarmContext.tsx                       MODIFY  three seeded collections and restoreDefaults deleted;
                                                   evaluation covers the whole feed (Task 23)
    AuthContext.tsx                        MODIFY  canAccessTab tab ids and plain names (Task 3);
                                                   every write method and the audit trail
                                                   deleted (Task 21)
  lib/
    alarms/evaluate.ts                     CREATE  conditionResult + evaluateFeed, pure (Task 23)
    csv/to-csv.ts                          CREATE  shared CSV serialiser, domain-free
    grafana/dashboards.ts                  CREATE  UIDs and variable names in one place
    health/relative-age.ts                 CREATE  "4 s ago", pure, clock passed in
    uns/historian-query.ts                 CREATE  form state, time bounds, /# rewrite
    uns/historian-csv.ts                   CREATE  the historian's CSV columns
    uns/tree-search.ts                     CREATE  ancestor expansion, loaded-node matching
    uns/topic-match.ts                     CREATE  MQTT +/# semantics, one tested matcher
    uns/base64.ts                          CREATE  byte length of a base64 string (Task 22)
    uns/map-nodes.ts                       MODIFY  no invented byte count, no online:true (Task 22)
    uns/isa95-probe.ts                     DELETE  fabricated children (Task 17)
  services/graphql/
    client.ts                              MODIFY  two observed timestamps (Task 19)
    queries.ts                             MODIFY  uuid and body dropped from the spB query (Task 22)
    types.ts                               MODIFY  GraphqlSpbNode loses uuid and body (Task 22)
  types/
    uns.ts                                 MODIFY  SystemHealthInfo gains three keys (Task 19);
                                                   SparkplugNode.online deleted (Task 22)
    rbac.ts                                MODIFY  AuditLogEntry deleted, no consumer (Task 21)
```

`ConnectionChip.tsx` stays in `common/` although spec section 17 lists it under `layout/`. Moving it would touch every import for no behavioural gain; the spec's grouping is descriptive, not a filesystem requirement.

`components/home/` keeps its leaf components — `NamespaceView` is a new shell around them, not a rewrite. `components/explore/` does not survive: once `ExploreView` is deleted the directory holds only the two historian components, so both move to `historian/` with `git mv` and the directory goes. A folder named after a menu item that no longer exists is the same class of untruth as a badge that lies.

Three view shells are deleted, each because something better replaces it: `SystemHealthView.tsx` by `HealthView`, which keeps its dashboard switcher and adds the three things Platform Observability needs around it; `HomeView.tsx` by `NamespaceView`; and `ExploreView.tsx` by `HistorianView`. None of the three is deleted for fabricating data — `SystemHealthView` in particular reads no `health` at all since commit `0812fc6e`, whatever the earlier audit said.

---

## Task 1: Eleven destinations, three redirects

The router, the tab-id map and the permission-gate names. Nothing renders differently yet except the URL — the destination views arrive in later tasks, so this task points the five new routes at placeholder shells that render an `EmptyState` naming the task that fills them. That keeps the app compiling and navigable at every commit.

**Files:**
- Modify: `11_frontend/src/App.tsx`
- Modify: `11_frontend/src/components/layout/AppLayout.tsx:32-51`
- Modify: `11_frontend/src/context/UNSContext.tsx:47`, `:299-340`
- Modify: `11_frontend/src/context/AuthContext.tsx:371-415`
- Create: `11_frontend/src/components/common/EmptyState.tsx`
- Test: `11_frontend/src/App.routes.test.tsx`

**Interfaces:**
- Consumes: nothing from the foundation plan.
- Produces:
  - `NavigationTab = 'plant' | 'shift' | 'alarms' | 'historian' | 'assets' | 'namespace' | 'sparkplug' | 'streams' | 'simulator' | 'health' | 'users'` exported from `src/context/UNSContext.tsx`.
  - `EmptyState` from `src/components/common/EmptyState.tsx`:
    ```ts
    interface EmptyStateProps {
      title: string;
      /** One sentence telling the operator what to do next. Not decoration. */
      detail: string;
      action?: { label: string; onClick: () => void };
    }
    export const EmptyState: React.FC<EmptyStateProps>;
    ```
  - Route paths every later task links to: `/plant`, `/shift`, `/alarms`, `/historian`, `/assets`, `/namespace`, `/sparkplug`, `/streams`, `/simulator`, `/health`, `/users`.

- [ ] **Step 1: Write the failing route test**

Create `11_frontend/src/App.routes.test.tsx`. It renders the real `App` at a hash and asserts the destination, so it needs the whole provider stack — which is why it mocks the client module wholesale rather than the transport.

```tsx
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./services/graphql/client', () => ({
  unsGraphQLClient: {
    getHealth: vi.fn().mockResolvedValue({
      status: 'DOWN', graphqlHttp: false, graphqlWs: false,
      lastPingMs: null, endpointUrl: 'http://localhost:8000/graphql',
    }),
    getUnsNodes: vi.fn().mockResolvedValue([]),
    getUnsNodeChildren: vi.fn().mockResolvedValue([]),
    getAlertRules: vi.fn().mockResolvedValue([]),
    subscribeToTopics: vi.fn(() => () => {}),
  },
}));

import App from './App';

const at = (hash: string) => {
  window.location.hash = hash;
  return render(<App />);
};

describe('console routes', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('uns_authenticated', 'true');
  });

  it('serves the plant destination', async () => {
    at('#/plant');
    expect(await screen.findByRole('heading', { name: /plant/i })).toBeInTheDocument();
  });

  it.each([
    ['#/tree', '/plant'],
    ['#/alerts', '/alarms'],
    ['#/system', '/health'],
  ])('redirects the retired path %s to %s', async (from, to) => {
    at(from);
    await screen.findByTestId('console-shell');
    expect(window.location.hash).toBe(`#${to}`);
  });

  it('serves every new destination', async () => {
    for (const path of ['/shift', '/assets', '/namespace', '/health']) {
      const view = at(`#${path}`);
      await screen.findByTestId('console-shell');
      expect(window.location.hash).toBe(`#${path}`);
      view.unmount();
    }
  });
});
```

The `uns_authenticated` key is what `AuthContext` restores a session from — confirm the exact key in `src/context/AuthContext.tsx` before running, and use whatever it actually reads. If the stored shape is richer than a boolean flag, write the shape the context expects; do not change the context to suit the test.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/App.routes.test.tsx
```

Expected: FAIL. `#/plant` has no route, so the layout renders nothing matching a "plant" heading.

- [ ] **Step 3: Add `EmptyState`**

Create `11_frontend/src/components/common/EmptyState.tsx`:

```tsx
import React from 'react';

interface EmptyStateProps {
  title: string;
  /** One sentence telling the operator what to do next. Not decoration. */
  detail: string;
  action?: { label: string; onClick: () => void };
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, detail, action }) => (
  <div
    className="flex h-full min-h-40 flex-col items-center justify-center gap-2 px-6 py-10 text-center"
    data-testid="empty-state"
  >
    <p className="text-[13px] font-semibold text-[#334155] dark:text-[#CBD5E1]">{title}</p>
    <p className="max-w-md text-[12px] leading-relaxed text-[#64748B] dark:text-[#94A3B8]">{detail}</p>
    {action && (
      <button
        type="button"
        onClick={action.onClick}
        className="mt-1 rounded border border-[#CBD5E1] px-2.5 py-1 text-[11px] font-medium text-[#334155] hover:bg-[#F1F5F9] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-[#334155] dark:text-[#CBD5E1] dark:hover:bg-[#1E293B]"
      >
        {action.label}
      </button>
    )}
  </div>
);
```

- [ ] **Step 4: Widen `NavigationTab`**

In `11_frontend/src/context/UNSContext.tsx`, replace line 47:

```ts
export type NavigationTab =
  | 'plant'
  | 'shift'
  | 'alarms'
  | 'historian'
  | 'assets'
  | 'namespace'
  | 'sparkplug'
  | 'streams'
  | 'simulator'
  | 'health'
  | 'users';
```

Then fix the initial value at `:119`:

```ts
const [activeTab, setActiveTab] = useState<NavigationTab>('plant');
```

And the four jump functions at `:299-340` — the hash targets move with the routes:

```ts
  const jumpToTopicInTree = async (targetTopic: string) => {
    setActiveTab('namespace');
    if (window.location.hash !== '#/namespace') {
      window.location.hash = '#/namespace';
    }
    // ...rest of the body unchanged
  };

  const jumpToHistorian = (topic: string) => {
    setHistorianInitialTopic(topic);
    setActiveTab('historian');
    window.location.hash = '#/historian';
  };
```

`jumpToSparkplug` and `jumpToKafkaTopic` keep their hashes; only their `setActiveTab` arguments are already valid (`'sparkplug'`, `'streams'`). Leave them.

- [ ] **Step 5: Rewrite the route table**

In `11_frontend/src/App.tsx`, replace the protected route block:

```tsx
        <Route element={<ProtectedConsoleLayout />}>
          {/* RUN THE PLANT */}
          <Route path="/plant" element={<PlantView />} />
          <Route path="/shift" element={<ShiftView />} />
          <Route path="/alarms" element={<AlarmManagementView />} />

          {/* UNDERSTAND THE DATA */}
          {/* Still the old screen. Task 18 replaces it with historian/HistorianView. */}
          <Route path="/historian" element={<ExploreView />} />
          <Route path="/assets" element={<AssetsView />} />
          <Route path="/namespace" element={<NamespaceView />} />

          {/* INTEGRATE */}
          <Route path="/sparkplug" element={<SparkplugView />} />
          <Route path="/streams" element={<KafkaStreamsView />} />
          {/* HashRouter, so this is #/simulator — the HTTP path stays / and does
              not collide with the /simulator proxy that reaches the control API. */}
          <Route path="/simulator" element={<SimulatorView />} />

          {/* PLATFORM */}
          <Route path="/health" element={<HealthView />} />
          <Route path="/users" element={<UserManagementView />} />

          {/* Retired paths. Bookmarks and the ADR-0007 nginx notes both reference
              these, so they redirect rather than 404. */}
          <Route path="/tree" element={<Navigate to="/plant" replace />} />
          <Route path="/alerts" element={<Navigate to="/alarms" replace />} />
          <Route path="/system" element={<Navigate to="/health" replace />} />
        </Route>
```

Add `Navigate` to the `react-router-dom` import if it is not already there, and check the existing index/catch-all routes point at `/plant` rather than `/tree`.

- [ ] **Step 6: Add the five placeholder shells**

Each is a real file at its final path so later tasks replace a body rather than create a file. Example — `11_frontend/src/components/plant/PlantView.tsx`:

```tsx
import React from 'react';
import { EmptyState } from '../common/EmptyState';

export const PlantView: React.FC = () => (
  <section className="flex h-full flex-col">
    <h1 className="px-4 py-2 text-[13px] font-semibold text-[#0F172A] dark:text-[#E2E8F0]">Plant</h1>
    <EmptyState
      title="Plant workspace not built yet"
      detail="Task 8 of the surfaces plan replaces this with the Asset canvas and its six tabs."
    />
  </section>
);
```

Repeat with the same shape for `shift/ShiftView.tsx` (heading `Shift & OEE`, Task 15), `assets/AssetsView.tsx` (heading `Assets`, Task 16), `namespace/NamespaceView.tsx` (heading `Namespace`, Task 17) and `health/HealthView.tsx` (heading `Health`, Task 19). Write each one out — do not import a shared placeholder, because each file gets fully replaced and a shared one would linger.

There is deliberately no shell for `/historian`. That route already has a working screen — `explore/ExploreView` — and replacing it with an empty state would take a capability away for seventeen commits. Task 18 rebuilds it in place.

- [ ] **Step 7: Retarget the tab-id map and add the shell test id**

In `11_frontend/src/components/layout/AppLayout.tsx`, replace `getTabIdFromPath` (`:32-41`):

```tsx
  // Route to permission id. Browser-local gating only — it is not enforced anywhere
  // server-side until the authentication cycle lands.
  const getTabIdFromPath = (path: string): string => {
    if (path.startsWith('/shift')) return 'shift';
    if (path.startsWith('/alarms')) return 'alarms';
    if (path.startsWith('/historian')) return 'historian';
    if (path.startsWith('/assets')) return 'assets';
    if (path.startsWith('/namespace')) return 'namespace';
    if (path.startsWith('/sparkplug')) return 'sparkplug';
    if (path.startsWith('/streams')) return 'streams';
    if (path.startsWith('/simulator')) return 'simulator';
    if (path.startsWith('/health')) return 'health';
    if (path.startsWith('/users')) return 'users';
    return 'plant';
  };
```

Change the redirect inside `AccessRestricted` (`:94`) from `'#/tree'` to `'#/plant'`, and add `data-testid="console-shell"` to the outermost wrapper element the component returns.

- [ ] **Step 8: Retarget `canAccessTab`**

In `11_frontend/src/context/AuthContext.tsx:371-415`, replace the switch. No new `FeatureKey` values: the eleven destinations map onto the eleven keys that already exist in `src/types/rbac.ts:7-20`. Adding keys would deepen a permission model the authentication cycle deletes, and this gate is browser-local and unenforced, so the mapping's only job is to stay coherent.

```ts
      let requiredFeature: FeatureKey = 'uns_tree';
      let featureName = 'Plant';

      switch (tab) {
        case 'plant':
        case 'assets':
        case 'namespace':
          requiredFeature = 'uns_tree';
          featureName = 'Plant, Assets and Namespace';
          break;
        case 'shift':
        case 'historian':
          // Shift results and Historic Events are both reads of recorded history.
          requiredFeature = 'historian';
          featureName = 'Historian and Shift results';
          break;
        case 'sparkplug':
          requiredFeature = 'sparkplug';
          featureName = 'Sparkplug';
          break;
        case 'streams':
          requiredFeature = 'streams';
          featureName = 'Streams';
          break;
        case 'alarms':
          requiredFeature = 'alarms';
          featureName = 'Alarms';
          break;
        case 'health':
          requiredFeature = 'system_ops';
          featureName = 'Health';
          break;
        case 'simulator':
          requiredFeature = 'simulator_ops';
          featureName = 'Simulator';
          break;
        case 'users':
          requiredFeature = 'user_management';
          featureName = 'Users';
          break;
      }
```

- [ ] **Step 9: Run the test and the type check**

```bash
cd 11_frontend && npx vitest run src/App.routes.test.tsx && npx tsc --noEmit
```

Expected: PASS, and no TypeScript errors. `tsc` will flag every remaining `setActiveTab('home')` / `'explore'` / `'system'` call site — fix each to the new member; there should be none left outside the files above, but the compiler is the authority.

- [ ] **Step 10: Prove no dead links remain**

```bash
cd 11_frontend && grep -rn "#/tree\|#/alerts\|#/system" src | grep -v "App.tsx"
```

Expected: no output. The three strings survive only as the redirect routes in `App.tsx`.

- [ ] **Step 11: Commit**

```bash
git add 11_frontend/src/App.tsx 11_frontend/src/App.routes.test.tsx \
  11_frontend/src/components/common/EmptyState.tsx \
  11_frontend/src/components/plant/PlantView.tsx \
  11_frontend/src/components/shift/ShiftView.tsx \
  11_frontend/src/components/assets/AssetsView.tsx \
  11_frontend/src/components/namespace/NamespaceView.tsx \
  11_frontend/src/components/health/HealthView.tsx \
  11_frontend/src/components/layout/AppLayout.tsx \
  11_frontend/src/context/UNSContext.tsx 11_frontend/src/context/AuthContext.tsx
git commit -m "feat(frontend): route the eleven console destinations

/plant, /shift, /assets, /namespace and /health join the router; /tree,
/alerts and /system redirect so existing bookmarks keep working. The five
new destinations are shells until their tasks land, so the app stays
navigable at every commit."
```

---

## Task 2: A shell that only says what it knows

The sidebar's four groups and the status footer. Every indicator in this task is either derived from `health` or deleted; nothing is reworded. This is spec section 18 test 8.

**Files:**
- Modify: `11_frontend/src/components/layout/Sidebar.tsx:36-46` (interface), `:60-141` (nav arrays), `:147` (`renderNavLink`), `:285-300` (group headings), `:348-395` (footer)
- Modify: `11_frontend/src/components/layout/AppLayout.tsx:104-121`
- Test: `11_frontend/src/components/layout/shell-truthfulness.test.tsx`

**Interfaces:**
- Consumes: `NavigationTab` and the `getTabIdFromPath` ids from Task 1; `SystemHealthInfo` narrowed to `{ status, graphqlHttp, graphqlWs, lastPingMs, endpointUrl }` by the foundation plan.
- Produces:
  - `NavGroup` and the widened `NavSectionItem` in `Sidebar.tsx`:
    ```ts
    interface NavSectionItem {
      to: string;
      tabId: string;
      label: string;
      shortLabel: string;
      icon: React.FC<{ className?: string }>;
      /** What an operator uses it for, in plant words. No product names. */
      description: string;
      featureKey: FeatureKey;
      /** A count an operator can act on, or undefined. Never a technology name. */
      badge?: number;
      adminOnly?: boolean;
    }
    interface NavGroup { heading: string; items: NavSectionItem[] }
    ```

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/layout/shell-truthfulness.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const health = {
  status: 'DOWN' as const,
  graphqlHttp: false,
  graphqlWs: false,
  lastPingMs: null,
  endpointUrl: 'http://localhost:8000/graphql',
};

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({
    health,
    allLoadedNodes: [],
    staleNodesCount: 0,
    bookmarks: [],
    settings: { organization: 'Test Plant' },
    setActiveTab: vi.fn(),
  }),
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    canAccessTab: () => ({ allowed: true, requiredFeature: 'uns_tree', featureName: 'Plant' }),
    currentUser: { name: 'Ada', role: 'operator', avatarColor: 'bg-amber-400' },
    isAdmin: true,
  }),
}));

vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ myUnacknowledgedCount: 0 }),
}));

import { Sidebar } from './Sidebar';

const renderSidebar = () =>
  render(
    <MemoryRouter initialEntries={['/plant']}>
      <Sidebar
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        isMobileOpen={false}
        onCloseMobile={vi.fn()}
        onOpenBookmarks={vi.fn()}
        onOpenStaleDrawer={vi.fn()}
      />
    </MemoryRouter>,
  );

describe('the console shell states nothing it has not observed', () => {
  beforeEach(() => localStorage.clear());

  it.each(['MQTT: ON', 'NEO4J: OK', 'KAFKA: ON', 'GQL 8000', 'ROOT'])(
    'never renders the fabricated indicator %s',
    (fabrication) => {
      const { container } = renderSidebar();
      expect(container.textContent).not.toContain(fabrication);
    },
  );

  it.each(['Timescale', 'v1.0', 'ADMIN', 'Protobuf', 'RBAC'])(
    'never labels a destination with the integrator term %s',
    (jargon) => {
      const { container } = renderSidebar();
      expect(container.textContent).not.toContain(jargon);
    },
  );

  it('names the eleven destinations in plant words', () => {
    renderSidebar();
    for (const name of [
      'Plant', 'Shift & OEE', 'Alarms', 'Historian', 'Assets',
      'Namespace', 'Sparkplug', 'Streams', 'Simulator', 'Health', 'Users',
    ]) {
      expect(screen.getByRole('link', { name: new RegExp(name, 'i') })).toBeInTheDocument();
    }
  });

  it('groups them under the four operator headings', () => {
    renderSidebar();
    for (const heading of ['Run the plant', 'Understand the data', 'Integrate', 'Platform']) {
      expect(screen.getByText(new RegExp(`^${heading}$`, 'i'))).toBeInTheDocument();
    }
  });

  it('reports the GraphQL endpoint state it was given, not a hardcoded one', () => {
    renderSidebar();
    expect(screen.getByTestId('sidebar-endpoint-state')).toHaveTextContent(/down/i);
  });
});
```

`getByRole('link', { name: /Plant/i })` matches the accessible name, which includes the description line. Keep descriptions free of other destinations' names or these queries go ambiguous — that is a feature, not a hazard to work around.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/layout/shell-truthfulness.test.tsx
```

Expected: FAIL on the first fabrication case — `MQTT: ON` is a literal in the footer at `Sidebar.tsx:362`.

- [ ] **Step 3: Replace the two nav arrays with four groups**

In `Sidebar.tsx`, replace `coreNavItems` and `opsNavItems` (`:60-141`) with one array of groups. Labels come from spec section 7; descriptions say what the destination answers, not which database it reads.

```tsx
  const navGroups: NavGroup[] = [
    {
      heading: 'Run the plant',
      items: [
        {
          to: '/plant', tabId: 'plant', label: 'Plant', shortLabel: 'Plant',
          icon: Factory, description: 'What a line is doing right now',
          featureKey: 'uns_tree',
        },
        {
          to: '/shift', tabId: 'shift', label: 'Shift & OEE', shortLabel: 'Shift',
          icon: Gauge, description: 'How the last shifts ran',
          featureKey: 'historian',
        },
        {
          to: '/alarms', tabId: 'alarms', label: 'Alarms', shortLabel: 'Alarms',
          icon: Bell, description: 'What needs attention',
          featureKey: 'alarms',
          badge: myUnacknowledgedCount > 0 ? myUnacknowledgedCount : undefined,
        },
      ],
    },
    {
      heading: 'Understand the data',
      items: [
        {
          to: '/historian', tabId: 'historian', label: 'Historian', shortLabel: 'Historian',
          icon: Search, description: 'Look up recorded Historic Events',
          featureKey: 'historian',
        },
        {
          to: '/assets', tabId: 'assets', label: 'Assets', shortLabel: 'Assets',
          icon: Boxes, description: 'The Asset Model and what is still unmodelled',
          featureKey: 'uns_tree',
        },
        {
          to: '/namespace', tabId: 'namespace', label: 'Namespace', shortLabel: 'Namespace',
          icon: Layers, description: 'Browse every published topic',
          featureKey: 'uns_tree',
          badge: allLoadedNodes.length > 0 ? allLoadedNodes.length : undefined,
        },
      ],
    },
    {
      heading: 'Integrate',
      items: [
        {
          to: '/sparkplug', tabId: 'sparkplug', label: 'Sparkplug', shortLabel: 'Sparkplug',
          icon: Radio, description: 'Edge nodes and their metrics',
          featureKey: 'sparkplug',
        },
        {
          to: '/streams', tabId: 'streams', label: 'Streams', shortLabel: 'Streams',
          icon: Workflow, description: 'Follow a topic as it flows downstream',
          featureKey: 'streams',
        },
        {
          to: '/simulator', tabId: 'simulator', label: 'Simulator', shortLabel: 'Simulator',
          icon: FlaskConical, description: 'Generate plant data for testing',
          featureKey: 'simulator_ops',
        },
      ],
    },
    {
      heading: 'Platform',
      items: [
        {
          to: '/health', tabId: 'health', label: 'Health', shortLabel: 'Health',
          icon: Activity, description: 'Is the console reaching the platform',
          featureKey: 'system_ops',
        },
        {
          to: '/users', tabId: 'users', label: 'Users', shortLabel: 'Users',
          icon: Shield, description: 'Who can see which screens',
          featureKey: 'user_management', adminOnly: true,
        },
      ],
    },
  ];
```

Update the `lucide-react` import: add `Factory`, `Gauge`, `Boxes`; drop `Database`, `Server`, `Zap` and any other icon that no longer has a call site. `npx tsc --noEmit` in Step 7 catches a stale import.

- [ ] **Step 4: Narrow the badge rendering and drop the jargon headings**

In `renderNavLink`, `item.badge` is now `number | undefined`, so the three-way colour switch on badge *text* is dead. Replace the badge block (`:200-216`) with:

```tsx
            {item.badge !== undefined && (
              <span
                className={`ml-1.5 shrink-0 rounded px-1.5 py-0.5 text-[11px] font-bold tabular-nums ${
                  isActive
                    ? 'bg-slate-950 text-amber-400 dark:bg-[#0B0B0C] dark:text-[#FFC107]'
                    : 'border border-[#CBD5E1] bg-slate-100 text-slate-700 dark:border-[#1E293B] dark:bg-[#0B0B0C] dark:text-[#94A3B8]'
                }`}
                title={item.tabId === 'alarms' ? 'Unacknowledged alarms assigned to you' : 'Loaded UNS Nodes'}
              >
                {item.badge}
              </span>
            )}
```

Fix `isActive` (`:151`) — `item.to === '/tree'` no longer exists:

```tsx
    const isActive = location.pathname === item.to || (item.to === '/plant' && location.pathname === '/');
```

Raise the description line from `text-[9px]` to `text-[11px]` in both the expanded row (`:191`) and the collapsed tooltip (`:227`), and the `(Locked)` marker (`:225`) likewise.

Then replace the two hardcoded group blocks (`:285-302`) with a loop over `navGroups`, so the `ISA-95` chip at `:288` disappears with them:

```tsx
        {navGroups.map((group, index) => (
          <div
            key={group.heading}
            className={`space-y-1 ${index > 0 ? 'border-t border-[#E2E8F0] pt-2 dark:border-[#1E293B]/70' : ''}`}
          >
            {!isCollapsed && (
              <div className="px-2 pb-1 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
                {group.heading}
              </div>
            )}
            {group.items
              .filter((item) => !item.adminOnly || isAdmin)
              .map(renderNavLink)}
          </div>
        ))}
```

Read how `adminOnly` behaved before this change — if the old code rendered admin-only items to everyone and relied on the lock icon, keep that, because changing who sees `/users` is not this task's business. Adjust the `.filter` accordingly and say which you kept in the commit message.

- [ ] **Step 5: Make the sidebar footer report the endpoint, not the stores**

Replace the expanded footer's first two blocks (`:350-370`) with one endpoint row. The browser can observe exactly one thing — whether its own two GraphQL transports answered — so that is all it claims. MQTT, Neo4j, Timescale and Kafka reachability is Prometheus and Grafana's job (`08_uns_observability`), and HEALTH links there.

```tsx
          <div className="flex items-center justify-between text-[11px] text-[#64748B]">
            <span className="font-semibold uppercase tracking-wider">GraphQL</span>
            <span
              data-testid="sidebar-endpoint-state"
              className={`flex items-center gap-1 font-bold ${
                health.status === 'LIVE'
                  ? 'text-emerald-600 dark:text-[#10B981]'
                  : health.status === 'DEGRADED'
                  ? 'text-amber-600 dark:text-[#FFC107]'
                  : 'text-rose-600 dark:text-rose-400'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  health.status === 'LIVE'
                    ? 'bg-emerald-500 dark:bg-[#10B981]'
                    : health.status === 'DEGRADED'
                    ? 'bg-amber-500 dark:bg-[#FFC107]'
                    : 'bg-rose-500'
                }`}
              />
              <span>
                {health.status === 'LIVE' ? 'Live' : health.status === 'DEGRADED' ? 'Degraded' : 'Down'}
              </span>
            </span>
          </div>
```

Delete the `ROOT` badge (`:387-391`) outright — the role already renders on the line above it. Raise the two `text-[8px]` spans in the user session bar (`:381`, `:384`) to `text-[11px]`. In the collapsed footer (`:395-402`), replace the unconditional green pulse with the same three-way colour and set `title={'GraphQL ' + health.status}`.

- [ ] **Step 6: Make the app footer report the same thing**

In `AppLayout.tsx`, replace the footer's two `<div>` groups (`:104-121`). `VITE: 3000` was wrong even as a guess (the dev port is 5173, per `src/lib/platform/settings.ts`), `SCHEMA: 2026.08.28-v2` is a frozen string with no source, `MODE: {health.mode}` reads a field the foundation plan deleted, `Connected to UNS Backend` is unconditional, and `Nodes: {allLoadedNodes.length || 28}` prints 28 when the real answer is 0.

```tsx
          <div className="flex items-center gap-3 sm:gap-4">
            <span className="font-medium text-[#334155] dark:text-[#94A3B8]" title={health.endpointUrl}>
              GraphQL: {health.endpointUrl}
            </span>
            {health.lastPingMs !== null && (
              <span className="hidden tabular-nums text-[#64748B] sm:inline">{health.lastPingMs} ms</span>
            )}
          </div>

          <div className="flex items-center gap-3 sm:gap-4">
            <ConnectionChip />
            <span className="font-medium tabular-nums text-[#334155] dark:text-[#94A3B8]">
              Nodes: {allLoadedNodes.length}
            </span>
            {staleNodesCount > 0 && (
              <span className="font-bold tabular-nums text-amber-600 dark:text-[#FFC107]">
                Stale: {staleNodesCount}
              </span>
            )}
          </div>
```

Import `ConnectionChip` from `'../common/ConnectionChip'`. Task 4 rebuilds it; here it just moves into the footer, where the shell's one connection claim belongs. Also raise the footer element's own `text-[9px]` (`:103`) to `text-[11px]`, and check `Header.tsx` does not already render a `ConnectionChip` — if it does, remove it there so the shell states its connection once.

- [ ] **Step 7: Run the test and the type check**

```bash
cd 11_frontend && npx vitest run src/components/layout/shell-truthfulness.test.tsx && npx tsc --noEmit
```

Expected: PASS. If the four-headings case fails on casing, the assertion is right and the markup is wrong — headings are uppercased by CSS, so the DOM text must be sentence case.

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/components/layout/ 11_frontend/src/components/common/Header.tsx
git commit -m "feat(frontend): group the nav by plant work and delete the invented shell state

MQTT: ON, NEO4J: OK, KAFKA: ON, GQL 8000, VITE: 3000, SCHEMA: 2026.08.28-v2,
MODE:, 'Connected to UNS Backend' and 'Nodes: ... || 28' were literals with no
observation behind them. The shell now reports only the GraphQL transport state
it measured. Badges naming technologies are gone; the two that remain are counts
an operator can act on."
```

---

## Task 3: Marketing claims the platform cannot support

`LandingView` and `LoginView` assert an SLA, a latency figure, a certification and a client list that no part of this repository measures or holds. They come out. What replaces them is what the platform genuinely is.

**Files:**
- Modify: `11_frontend/src/components/landing/LandingView.tsx:68-76`, `:130-158`, `:263-271`, `:589-597`
- Modify: `11_frontend/src/components/auth/LoginView.tsx:242-248`
- Modify: `11_frontend/src/context/AuthContext.tsx:73`
- Test: `11_frontend/src/components/landing/landing-claims.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/landing/landing-claims.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, currentUser: null, login: vi.fn() }),
}));

import { LandingView } from './LandingView';
import { LoginView } from '../auth/LoginView';

const UNSUPPORTABLE = [
  '99.999%',
  'Message Delivery SLA',
  '< 5 ms',
  'ISO/IEC 62443',
  'Certified',
  'Zero-Trust',
  'immutable audit logs',
  'non-repudiable',
  'Automotive, Chemicals, Pharma',
];

describe('the console claims nothing the platform does not do', () => {
  it.each(UNSUPPORTABLE)('the landing page does not claim %s', (claim) => {
    const { container } = render(<MemoryRouter><LandingView /></MemoryRouter>);
    expect(container.textContent).not.toContain(claim);
  });

  it.each(['ISO/IEC 62443', 'TLS 1.3', 'Security Auditing Enabled'])(
    'the sign-in page does not claim %s',
    (claim) => {
      const { container } = render(<MemoryRouter><LoginView /></MemoryRouter>);
      expect(container.textContent).not.toContain(claim);
    },
  );

  it('says on the sign-in page that roles are not server-enforced', () => {
    const { container } = render(<MemoryRouter><LoginView /></MemoryRouter>);
    expect(container.textContent).toMatch(/not yet enforced by the server/i);
  });
});
```

Confirm both components' real export names and required props before running. If either needs `AlarmProvider` or `UNSProvider`, mock those modules the way Task 2 does rather than rendering real providers.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/landing/landing-claims.test.tsx
```

Expected: FAIL on `99.999%` first.

- [ ] **Step 3: Replace the four statistics with four true statements**

`LandingView.tsx:130-158`. Each replacement is verifiable from this repository, and none is a performance figure, because nothing here measures performance.

```tsx
      {/* What the platform is. Verifiable in this repository; no SLA, latency or
          compliance claim, because nothing in the stack measures one. */}
      <section className="border-y border-[#E2E8F0] bg-white px-4 py-8 dark:border-[#1E293B] dark:bg-[#0B0B0C] sm:px-8">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 text-center md:grid-cols-4">
          <div>
            <div className="font-serif text-2xl font-bold text-[#0F172A] dark:text-[#F8FAFC] sm:text-3xl">
              ISA-95
            </div>
            <div className="mt-1 text-xs font-medium text-[#64748B]">One topic hierarchy the whole plant shares</div>
          </div>
          <div>
            <div className="font-serif text-2xl font-bold text-amber-600 dark:text-[#FFC107] sm:text-3xl">
              Three projections
            </div>
            <div className="mt-1 text-xs font-medium text-[#64748B]">Current state, history and event log from one publish</div>
          </div>
          <div>
            <div className="font-serif text-2xl font-bold text-[#0F172A] dark:text-[#F8FAFC] sm:text-3xl">
              One read surface
            </div>
            <div className="mt-1 text-xs font-medium text-[#64748B]">GraphQL queries, mutations and subscriptions</div>
          </div>
          <div>
            <div className="font-serif text-2xl font-bold text-emerald-600 dark:text-emerald-400 sm:text-3xl">
              Open standards
            </div>
            <div className="mt-1 text-xs font-medium text-[#64748B]">MQTT, Sparkplug B, OPC UA, Kafka</div>
          </div>
        </div>
      </section>
```

- [ ] **Step 4: Rewrite the security section as what it is**

`LandingView.tsx:589-597` claims a certification and an architecture the repo does not implement. Until the authentication cycle lands, the honest version describes the access model that exists:

```tsx
          <div className="text-xs font-mono font-semibold uppercase tracking-wider text-amber-600 dark:text-[#FFC107]">
            Access
          </div>
          <h2 className="font-serif text-2xl font-bold text-[#0F172A] dark:text-[#F8FAFC] sm:text-3xl">
            Every screen behind a role
          </h2>
          <p className="text-xs text-[#475569] dark:text-[#94A3B8] sm:text-sm">
            Roles decide which destinations a person sees, and Alert Rule changes are recorded
            with who made them. Sign-in is not yet backed by an identity provider — Health
            lists exactly what is and is not enforced.
          </p>
```

Apply the same treatment at `:263-271`: keep the sentence about the permission matrix and the five roles — both true, see `src/types/rbac.ts` — and delete `immutable audit logs` plus the `ISO/IEC 62443 Cybersecurity` line beneath it.

- [ ] **Step 5: Fix the hero and the sign-in notice**

`LandingView.tsx:72` asserts `ISO/IEC 62443 security across every manufacturing site`. Replace the `description` prop:

```tsx
        description="Publish shop-floor data once to a Unified Namespace and read it anywhere: a graph of current state, a time-series history, and an event log, all through one GraphQL surface."
```

Leave `badgeText`, `title`, `titleLine2` and the button copy — they describe the product accurately.

`LoginView.tsx:242-248` — the console cannot know its transport is TLS 1.3, and nothing here audits to 62443:

```tsx
          {/* Sign-in is browser-local until the authentication cycle lands. Saying so
              is the only honest thing this box can do. */}
          <div className="flex items-center justify-between rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-3 text-[11px] text-[#64748B] dark:border-[#1E293B] dark:bg-[#0B0B0C]">
            <div className="flex items-center gap-2">
              <Shield className="h-3.5 w-3.5 text-amber-600 dark:text-[#FFC107]" />
              <span>Roles are applied in this browser and are not yet enforced by the server</span>
            </div>
          </div>
```

- [ ] **Step 6: Rename the seeded user's department**

`AuthContext.tsx:73` gives a seeded user the department `ISO/IEC 62443 Compliance`. The
string is the same claim as the others, just wearing a job title, and it renders in
`/users` and the session menu. Replace it with a department a plant actually has:

```ts
    department: 'Plant IT',
```

Change nothing else about the seeded users — Task 21 reduces `/users`, and the
authentication cycle replaces the whole list with the realm's.

- [ ] **Step 7: Run the test**

```bash
cd 11_frontend && npx vitest run src/components/landing/landing-claims.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Sweep the whole module for survivors**

```bash
cd 11_frontend && grep -rn "62443\|99\.999\|TLS 1\.3\|Zero-Trust\|non-repudiable\|Certified" src
```

Expected: no output. If a string survives in a component the test does not render, fix it the same way and add that component to the test.

- [ ] **Step 9: Commit**

```bash
git add 11_frontend/src/components/landing/ 11_frontend/src/components/auth/LoginView.tsx   11_frontend/src/context/AuthContext.tsx
git commit -m "fix(frontend): stop claiming an SLA, a latency and a certification

99.999%, < 5 ms, ISO/IEC 62443, Zero-Trust, TLS 1.3 and the client list were
copy with nothing behind them - this repository measures no delivery rate, no
latency and no compliance. The replacements describe the architecture, which is
verifiable, and the sign-in notice now says roles are not server-enforced."
```

---

## Task 4: One connection chip that names which half failed

`ConnectionChip` currently reads `health.mode` (deleted by the foundation plan) and prints `Fallback Mock Engine` and `Simulated Reactive Feed` when a transport is down — neither exists; there is no mock engine and no simulated feed. This task rebuilds the chip on `connectionState()` and covers spec section 18 test 7.

**Files:**
- Modify: `11_frontend/src/components/common/ConnectionChip.tsx:12-32`, `:52-60`, `:71-108`
- Test: `11_frontend/src/components/common/ConnectionChip.test.tsx`

**Interfaces:**
- Consumes: `connectionState(health): { status: 'LIVE' | 'CONNECTING' | 'DEGRADED' | 'DOWN'; label: string; detail: string }` from `src/lib/health/connection-state.ts`, and the narrowed `SystemHealthInfo`. Both from the foundation plan.
- Produces: nothing other tasks import. Task 2 already placed the chip in the app footer; Task 19 links to it from HEALTH.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/common/ConnectionChip.test.tsx`. The four cases are exactly spec section 12's table.

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { SystemHealthInfo } from '../../types/uns';

const health: { current: SystemHealthInfo } = {
  current: {
    status: 'LIVE', graphqlHttp: true, graphqlWs: true,
    lastPingMs: 12, endpointUrl: 'http://localhost:8000/graphql',
  },
};

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({
    health: health.current,
    settings: { graphqlUrl: '/graphql', graphqlWsUrl: 'ws://localhost:8000/graphql' },
    updateSettings: vi.fn(),
    refreshTree: vi.fn(),
  }),
}));

import { ConnectionChip } from './ConnectionChip';

const renderWith = (patch: Partial<SystemHealthInfo>) => {
  health.current = { ...health.current, ...patch };
  return render(<ConnectionChip />);
};

describe('the connection chip', () => {
  it('reads Live when both transports answer', () => {
    renderWith({ status: 'LIVE', graphqlHttp: true, graphqlWs: true });
    expect(screen.getByTestId('connection-chip')).toHaveTextContent(/^Live/);
  });

  it('names the WebSocket when only it is down', () => {
    renderWith({ status: 'DEGRADED', graphqlHttp: true, graphqlWs: false });
    expect(screen.getByTestId('connection-chip')).toHaveTextContent('Degraded — live updates offline');
  });

  it('names the queries when only they fail', () => {
    renderWith({ status: 'DEGRADED', graphqlHttp: false, graphqlWs: true });
    expect(screen.getByTestId('connection-chip')).toHaveTextContent('Degraded — queries failing');
  });

  it('reads Down when neither answers', () => {
    renderWith({ status: 'DOWN', graphqlHttp: false, graphqlWs: false });
    expect(screen.getByTestId('connection-chip')).toHaveTextContent('Down — no connection to GraphQL');
  });

  it.each(['Fallback Mock Engine', 'Simulated Reactive Feed', 'SIM', 'LIVE_GRAPHQL'])(
    'never claims %s',
    async (fabrication) => {
      const { container } = renderWith({ status: 'DEGRADED', graphqlHttp: true, graphqlWs: false });
      await userEvent.click(screen.getByTestId('connection-chip'));
      expect(container.textContent).not.toContain(fabrication);
    },
  );

  it('shows the endpoint and the latency in the popover', async () => {
    renderWith({ status: 'LIVE', graphqlHttp: true, graphqlWs: true, lastPingMs: 12 });
    await userEvent.click(screen.getByTestId('connection-chip'));
    expect(screen.getByText('http://localhost:8000/graphql')).toBeInTheDocument();
    expect(screen.getByText('12 ms')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/common/ConnectionChip.test.tsx
```

Expected: FAIL — there is no `connection-chip` test id, and `health.mode` no longer type-checks.

- [ ] **Step 3: Drive the chip from `connectionState()`**

Replace `getStatusColor` and `getStatusDot` (`:12-32`) with one lookup keyed on `ConnectionStatus`, and derive everything shown from `connectionState`:

```tsx
import { connectionState } from '../../lib/health/connection-state';
import type { ConnectionStatus } from '../../types/uns';

const TONE: Record<ConnectionStatus, { chip: string; dot: string }> = {
  LIVE: {
    chip: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-500/30',
    dot: 'bg-emerald-500 dark:bg-emerald-400',
  },
  DEGRADED: {
    chip: 'bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-[#FFC107] border-amber-300 dark:border-amber-500/30',
    dot: 'bg-amber-500 dark:bg-[#FFC107]',
  },
  DOWN: {
    chip: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-300 dark:border-rose-500/30',
    dot: 'bg-rose-500',
  },
};
```

Inside the component, above the return:

```tsx
  const state = connectionState(health);
  const tone = TONE[state.status];
```

`ConnectionStatus` has exactly three members — `LIVE`, `DEGRADED`, `DOWN` — and spec section 12's four rows collapse onto them, so `TONE` is exhaustive and no state pulses. A pulsing dot only carries information when it means "waiting", and none of these three is waiting.

- [ ] **Step 4: Replace the chip face**

`:49-60` becomes:

```tsx
      <button
        id="connection-status-chip"
        data-testid="connection-chip"
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-all ${tone.chip} cursor-pointer hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500`}
        title={state.detail}
      >
        <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
        <span className="font-semibold">{state.detail}</span>
      </button>
```

`state.detail` is the full sentence from spec section 12 — `Live`, `Degraded — live updates offline`, `Degraded — queries failing`, `Down — no connection to GraphQL`. It is short enough for the footer, and shortening it to a word is exactly the flattening this task exists to undo.

- [ ] **Step 5: Replace the popover's subsystem block**

`:71-108`. The heading loses the module name (`07_uns_graphql` means nothing to an operator), the two transport rows say what happened rather than inventing a fallback, and the `Data source mode` row goes because the field is gone.

```tsx
          <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-3 dark:border-[#1E293B]">
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-amber-600 dark:text-[#FFC107]" />
              <span className="text-[13px] font-bold text-[#0F172A] dark:text-[#F8FAFC]">Connection</span>
            </div>
            <span className={`rounded border px-2 py-0.5 text-[11px] font-bold ${tone.chip}`}>
              {state.label}
            </span>
          </div>

          <div className="space-y-2 border-b border-[#E2E8F0] py-3 text-[12px] dark:border-[#1E293B]">
            <div className="flex items-center justify-between text-[#475569] dark:text-[#94A3B8]">
              <span className="flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5 text-[#64748B]" />
                <span>Queries (HTTP POST)</span>
              </span>
              <span className={health.graphqlHttp ? 'font-bold text-emerald-600 dark:text-emerald-400' : 'font-bold text-rose-600 dark:text-rose-400'}>
                {health.graphqlHttp ? 'Answering' : 'Not answering'}
              </span>
            </div>

            <div className="flex items-center justify-between text-[#475569] dark:text-[#94A3B8]">
              <span className="flex items-center gap-1.5">
                <Wifi className="h-3.5 w-3.5 text-[#64748B]" />
                <span>Live updates (WebSocket)</span>
              </span>
              <span className={health.graphqlWs ? 'font-bold text-emerald-600 dark:text-emerald-400' : 'font-bold text-rose-600 dark:text-rose-400'}>
                {health.graphqlWs ? 'Subscribed' : 'Disconnected'}
              </span>
            </div>

            <div className="flex items-center justify-between pt-1 text-[12px] text-[#64748B]">
              <span>Round-trip</span>
              <span className="font-semibold tabular-nums text-[#0F172A] dark:text-[#F8FAFC]">
                {health.lastPingMs === 0 ? '—' : `${health.lastPingMs} ms`}
              </span>
            </div>

            <div className="flex items-center justify-between gap-2 text-[12px] text-[#64748B]">
              <span className="shrink-0">Endpoint</span>
              <span className="truncate font-mono text-[11px] text-[#0F172A] dark:text-[#F8FAFC]" title={health.endpointUrl}>
                {health.endpointUrl}
              </span>
            </div>
          </div>
```

Raise every remaining `text-[10px]` in the popover's configuration form (`:113`, `:115`, `:126`) to `text-[11px]`.

- [ ] **Step 6: Run the test and the type check**

```bash
cd 11_frontend && npx vitest run src/components/common/ConnectionChip.test.tsx && npx tsc --noEmit
```

Expected: PASS with no type errors.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/components/common/ConnectionChip.tsx 11_frontend/src/components/common/ConnectionChip.test.tsx
git commit -m "feat(frontend): the connection chip names which half of GraphQL failed

An operator whose WebSocket dropped is reading values that stopped updating
while every query still works, and one green dot cannot tell them that. The chip
now renders the four states from the spec verbatim. 'Fallback Mock Engine' and
'Simulated Reactive Feed' are gone - there is no mock engine and no simulated
feed."
```

---

## Task 5: The four primitives every surface reuses

`StatusPill`, `ValueWithUnit` and `DataTable`. Written once here so that null-safety, tabular numerals and the type scale are decided in one place rather than re-argued in eleven views. `EmptyState` already exists from Task 1.

**Files:**
- Create: `11_frontend/src/components/common/StatusPill.tsx`
- Create: `11_frontend/src/components/common/ValueWithUnit.tsx`
- Create: `11_frontend/src/components/common/DataTable.tsx`
- Test: `11_frontend/src/components/common/primitives.test.tsx`

**Interfaces:**
- Consumes: `NO_VALUE` from `src/lib/oee/format.ts` (the em dash, foundation plan).
- Produces:
  ```ts
  // StatusPill.tsx
  export type PillTone = 'good' | 'warn' | 'bad' | 'neutral' | 'info';
  export const StatusPill: React.FC<{ label: string; tone: PillTone; title?: string }>;

  // ValueWithUnit.tsx — renders NO_VALUE for null/undefined, never 0
  export const ValueWithUnit: React.FC<{
    value: number | string | null | undefined;
    unit?: string | null;
    /** Fixed decimals for numbers. Strings pass through untouched. */
    decimals?: number;
    /** true when the Metric has no Metric Definition, so the unit is unknown */
    unenriched?: boolean;
  }>;

  // DataTable.tsx
  export interface Column<T> {
    key: string;
    header: string;
    /** right for numbers, left for text. Numbers get tabular numerals. */
    align?: 'left' | 'right';
    /** monospace for topics, metric keys and ids */
    mono?: boolean;
    render: (row: T) => React.ReactNode;
  }
  export function DataTable<T>(props: {
    columns: Column<T>[];
    rows: T[];
    rowKey: (row: T) => string;
    onRowClick?: (row: T) => void;
    selectedKey?: string;
    empty: React.ReactNode;
  }): React.ReactElement;
  ```

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/common/primitives.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { StatusPill } from './StatusPill';
import { ValueWithUnit } from './ValueWithUnit';
import { DataTable, type Column } from './DataTable';

describe('ValueWithUnit', () => {
  it('renders an em dash for null, not zero', () => {
    const { container } = render(<ValueWithUnit value={null} unit="degC" />);
    expect(container.textContent).toContain('—');
    expect(container.textContent).not.toContain('0');
  });

  it('renders a real zero as zero', () => {
    render(<ValueWithUnit value={0} unit="bar" decimals={1} />);
    expect(screen.getByText('0.0')).toBeInTheDocument();
    expect(screen.getByText('bar')).toBeInTheDocument();
  });

  it('marks a metric with no Metric Definition as unenriched', () => {
    render(<ValueWithUnit value={42} unenriched />);
    expect(screen.getByTitle(/no metric definition/i)).toBeInTheDocument();
  });

  it('omits the unit when there is none', () => {
    const { container } = render(<ValueWithUnit value={7} />);
    expect(container.textContent).toBe('7');
  });
});

describe('DataTable', () => {
  interface Row { id: string; topic: string; count: number }
  const columns: Column<Row>[] = [
    { key: 'topic', header: 'Topic', mono: true, render: (r) => r.topic },
    { key: 'count', header: 'Events', align: 'right', render: (r) => r.count },
  ];
  const rows: Row[] = [
    { id: 'a', topic: 'plant/line1/temp', count: 3 },
    { id: 'b', topic: 'plant/line1/press', count: 11 },
  ];

  it('renders the empty node instead of an empty tbody', () => {
    render(
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} empty={<p>No rows loaded</p>} />,
    );
    expect(screen.getByText('No rows loaded')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /plant/ })).not.toBeInTheDocument();
  });

  it('right-aligns numeric columns with tabular numerals', () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} empty={null} />);
    const cell = screen.getByText('11');
    expect(cell.className).toContain('text-right');
    expect(cell.className).toContain('tabular-nums');
  });

  it('reports the clicked row and marks the selected one', async () => {
    const onRowClick = vi.fn();
    render(
      <DataTable
        columns={columns} rows={rows} rowKey={(r) => r.id}
        onRowClick={onRowClick} selectedKey="b" empty={null}
      />,
    );
    await userEvent.click(screen.getByText('plant/line1/temp'));
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
    expect(screen.getByText('plant/line1/press').closest('tr')).toHaveAttribute('aria-selected', 'true');
  });
});

describe('StatusPill', () => {
  it('exposes its explanation as a title', () => {
    render(<StatusPill label="Restated" tone="warn" title="Revision 2, recomputed after late data" />);
    expect(screen.getByTitle(/revision 2/i)).toHaveTextContent('Restated');
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/common/primitives.test.tsx
```

Expected: FAIL — none of the three modules exist.

- [ ] **Step 3: Write `StatusPill`**

```tsx
import React from 'react';

export type PillTone = 'good' | 'warn' | 'bad' | 'neutral' | 'info';

const TONE: Record<PillTone, string> = {
  good: 'bg-emerald-50 text-emerald-700 border-emerald-300 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30',
  warn: 'bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-500/10 dark:text-[#FFC107] dark:border-amber-500/30',
  bad: 'bg-rose-50 text-rose-700 border-rose-300 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/30',
  neutral: 'bg-slate-100 text-slate-700 border-[#CBD5E1] dark:bg-[#0B0B0C] dark:text-[#94A3B8] dark:border-[#1E293B]',
  info: 'bg-sky-50 text-sky-700 border-sky-300 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/30',
};

export const StatusPill: React.FC<{ label: string; tone: PillTone; title?: string }> = ({
  label,
  tone,
  title,
}) => (
  <span
    title={title}
    className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[11px] font-semibold ${TONE[tone]}`}
  >
    {label}
  </span>
);
```

- [ ] **Step 4: Write `ValueWithUnit`**

```tsx
import React from 'react';
import { NO_VALUE } from '../../lib/oee/format';

interface ValueWithUnitProps {
  value: number | string | null | undefined;
  unit?: string | null;
  /** Fixed decimals for numbers. Strings pass through untouched. */
  decimals?: number;
  /** true when the Metric has no Metric Definition, so the unit is unknown */
  unenriched?: boolean;
}

export const ValueWithUnit: React.FC<ValueWithUnitProps> = ({
  value,
  unit,
  decimals,
  unenriched,
}) => {
  // null and undefined are absent readings. 0 is a reading. Conflating them is
  // the failure ADR-0008 exists to prevent, so the check is explicit.
  const absent = value === null || value === undefined;
  const text = absent
    ? NO_VALUE
    : typeof value === 'number' && decimals !== undefined
    ? value.toFixed(decimals)
    : String(value);

  return (
    <span className="inline-flex items-baseline gap-1">
      <span className={`tabular-nums ${absent ? 'text-[#94A3B8]' : ''}`}>{text}</span>
      {!absent && unit && <span className="text-[11px] text-[#64748B]">{unit}</span>}
      {unenriched && (
        <span
          className="text-[11px] text-[#94A3B8]"
          title="No Metric Definition — raw value, unit unknown"
        >
          raw
        </span>
      )}
    </span>
  );
};
```

- [ ] **Step 5: Write `DataTable`**

```tsx
import React from 'react';

export interface Column<T> {
  key: string;
  header: string;
  /** right for numbers, left for text. Numbers get tabular numerals. */
  align?: 'left' | 'right';
  /** monospace for topics, metric keys and ids */
  mono?: boolean;
  render: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedKey?: string;
  empty: React.ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  empty,
}: DataTableProps<T>): React.ReactElement {
  if (rows.length === 0) return <>{empty}</>;

  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 z-10 bg-[#F8FAFC] dark:bg-[#0B0B0C]">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`border-b border-[#E2E8F0] px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[#64748B] dark:border-[#1E293B] ${
                  column.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const isSelected = key === selectedKey;
            return (
              <tr
                key={key}
                aria-selected={isSelected}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                className={`border-b border-[#F1F5F9] dark:border-[#1E293B]/60 ${
                  onRowClick ? 'cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500' : ''
                } ${
                  isSelected
                    ? 'bg-amber-50 dark:bg-[#FFC107]/10'
                    : onRowClick
                    ? 'hover:bg-[#F8FAFC] dark:hover:bg-[#1E293B]/40'
                    : ''
                }`}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-2 py-1 align-top text-[#334155] dark:text-[#CBD5E1] ${
                      column.align === 'right' ? 'text-right tabular-nums' : 'text-left'
                    } ${column.mono ? 'font-mono' : ''}`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

The right-alignment test asserts the class is on the element carrying the text, so `render` must not wrap the value in another element for that column — in the test it returns a bare number, which React renders as a text node inside the `<td>`. If `getByText('11')` resolves to the `<td>`, the assertion passes as written.

- [ ] **Step 6: Run the test**

```bash
cd 11_frontend && npx vitest run src/components/common/primitives.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/components/common/StatusPill.tsx \
  11_frontend/src/components/common/ValueWithUnit.tsx \
  11_frontend/src/components/common/DataTable.tsx \
  11_frontend/src/components/common/primitives.test.tsx
git commit -m "feat(frontend): add the shared table, value and pill primitives

Null-safety, tabular numerals, sticky headers, focus rings and the 11/12/13px
type scale are decided once here instead of eleven times across the views.
ValueWithUnit distinguishes an absent reading from a zero reading explicitly,
because that distinction is what ADR-0008 is about."
```

---

## Task 6: One Grafana embed, three call sites

PLANT ▸ Trend, SHIFT and HEALTH all embed a dashboard. The sub-path, kiosk parameter, theme and the deep-link variables get decided once.

**`GrafanaEmbed` already exists.** Commit `0812fc6e` added `src/components/common/GrafanaEmbed.tsx` with `GRAFANA_DASHBOARDS`, `GrafanaDashboardId`, `grafanaKioskPath(uid, theme)` and a plain iframe, and `system/SystemHealthView.tsx` is its one current caller. Read it first. What it cannot do is the reason this task exists: it takes no dashboard variables, so no call site can deep-link to an Asset or a Metric, and it has no failure state, so the ADR-0007 fall-through renders the console inside itself with no explanation. This task rewrites it and moves the URL construction into a tested module.

Nothing here invents a variable: `var-asset` exists on `uns-oee`, `var-topic` and `var-metric` on `uns-process-visualization`, and `uns-platform-observability` has none.

**Files:**
- Create: `11_frontend/src/lib/grafana/dashboards.ts`
- Modify: `11_frontend/src/components/common/GrafanaEmbed.tsx` — rewritten body, `GRAFANA_DASHBOARDS` and `grafanaKioskPath` move to `lib/grafana/dashboards.ts`
- Modify: `11_frontend/src/components/system/SystemHealthView.tsx` — the one existing caller, so it keeps compiling until Task 19 deletes it
- Test: `11_frontend/src/lib/grafana/dashboards.test.ts`
- Test: `11_frontend/src/components/common/GrafanaEmbed.test.tsx`

**Interfaces:**
- Consumes: the console theme, and the `/grafana` proxy that is already in `nginx.conf` and `vite.config.ts`. The browser only ever uses the relative `/grafana` path, so it reads no host or port setting at all. Foundation Task 12 verifies the proxy and configures `urls.grafana_proxy_target`; it adds nothing this component reads.
- Produces:
  ```ts
  // lib/grafana/dashboards.ts
  export const GRAFANA_BASE = '/grafana';
  export type DashboardUid = 'uns-oee' | 'uns-process-visualization' | 'uns-platform-observability';
  export interface EmbedOptions {
    uid: DashboardUid;
    /** Only the variables that dashboard defines. Anything else throws. */
    variables?: Record<string, string>;
    from?: string;
    to?: string;
    theme: 'light' | 'dark';
  }
  export function dashboardUrl(options: EmbedOptions): string;
  /** The switcher's three entries, moved here from GrafanaEmbed.tsx unchanged. */
  export const GRAFANA_DASHBOARDS: Record<'platform' | 'process' | 'oee', { uid: DashboardUid; label: string }>;
  export type GrafanaDashboardId = keyof typeof GRAFANA_DASHBOARDS;

  // components/common/GrafanaEmbed.tsx
  export const GrafanaEmbed: React.FC<EmbedOptions & { title: string; className?: string }>;
  ```

- [ ] **Step 1: Write the failing URL test**

Create `11_frontend/src/lib/grafana/dashboards.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { dashboardUrl } from './dashboards';

describe('dashboardUrl', () => {
  it('builds a kiosk URL under the console proxy path', () => {
    const url = new URL(dashboardUrl({ uid: 'uns-platform-observability', theme: 'dark' }), 'http://console');
    expect(url.pathname).toBe('/grafana/d/uns-platform-observability');
    expect(url.searchParams.get('kiosk')).toBe('1');
    expect(url.searchParams.get('theme')).toBe('dark');
  });

  it('passes the variables the OEE dashboard defines', () => {
    const url = new URL(
      dashboardUrl({
        uid: 'uns-oee',
        variables: { asset: 'CovestroAG/Dormagen/Production/Line1' },
        from: 'now-7d', to: 'now', theme: 'light',
      }),
      'http://console',
    );
    expect(url.searchParams.get('var-asset')).toBe('CovestroAG/Dormagen/Production/Line1');
    expect(url.searchParams.get('from')).toBe('now-7d');
    expect(url.searchParams.get('to')).toBe('now');
  });

  it('passes topic and metric to the process visualization dashboard', () => {
    const url = new URL(
      dashboardUrl({
        uid: 'uns-process-visualization',
        variables: { topic: 'plant/line1/temp', metric: 'temperature' },
        theme: 'dark',
      }),
      'http://console',
    );
    expect(url.searchParams.get('var-topic')).toBe('plant/line1/temp');
    expect(url.searchParams.get('var-metric')).toBe('temperature');
  });

  it('refuses a variable the dashboard does not define', () => {
    expect(() =>
      dashboardUrl({ uid: 'uns-platform-observability', variables: { asset: 'x' }, theme: 'dark' }),
    ).toThrow(/uns-platform-observability/);
    expect(() =>
      dashboardUrl({ uid: 'uns-oee', variables: { topic: 'x' }, theme: 'dark' }),
    ).toThrow(/var-topic/);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/grafana/dashboards.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write `dashboards.ts`**

```ts
/**
 * The three provisioned dashboards and the variables each one actually defines.
 * Verified against 08_uns_observability/grafana/dashboards/*.json — a deep link
 * that sets a variable the dashboard does not declare is silently ignored by
 * Grafana, which looks like a broken filter, so this module throws instead.
 */
export const GRAFANA_BASE = '/grafana';

export type DashboardUid = 'uns-oee' | 'uns-process-visualization' | 'uns-platform-observability';

const VARIABLES: Record<DashboardUid, readonly string[]> = {
  'uns-oee': ['asset'],
  'uns-process-visualization': ['topic', 'metric'],
  'uns-platform-observability': [],
};

export interface EmbedOptions {
  uid: DashboardUid;
  /** Only the variables that dashboard defines. Anything else throws. */
  variables?: Record<string, string>;
  from?: string;
  to?: string;
  theme: 'light' | 'dark';
}

/** Moved from GrafanaEmbed.tsx unchanged, so SystemHealthView's switcher keeps working. */
export const GRAFANA_DASHBOARDS = {
  platform: { uid: 'uns-platform-observability', label: 'Platform' },
  process: { uid: 'uns-process-visualization', label: 'Process' },
  oee: { uid: 'uns-oee', label: 'OEE' },
} as const satisfies Record<string, { uid: DashboardUid; label: string }>;

export type GrafanaDashboardId = keyof typeof GRAFANA_DASHBOARDS;

export function dashboardUrl({ uid, variables, from, to, theme }: EmbedOptions): string {
  const allowed = VARIABLES[uid];
  const params = new URLSearchParams({ kiosk: '1', theme });

  for (const [name, value] of Object.entries(variables ?? {})) {
    if (!allowed.includes(name)) {
      throw new Error(
        `Dashboard ${uid} does not define var-${name}. It defines: ${
          allowed.length ? allowed.map((v) => `var-${v}`).join(', ') : 'no variables'
        }.`,
      );
    }
    params.set(`var-${name}`, value);
  }

  if (from) params.set('from', from);
  if (to) params.set('to', to);

  return `${GRAFANA_BASE}/d/${uid}?${params.toString()}`;
}
```

- [ ] **Step 4: Write the failing embed test**

Create `11_frontend/src/components/common/GrafanaEmbed.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GrafanaEmbed } from './GrafanaEmbed';

describe('GrafanaEmbed', () => {
  it('renders a titled iframe at the built URL', () => {
    render(<GrafanaEmbed uid="uns-oee" variables={{ asset: 'Line1' }} theme="dark" title="Shift OEE" />);
    const frame = screen.getByTitle('Shift OEE');
    expect(frame.getAttribute('src')).toContain('/grafana/d/uns-oee?');
    expect(frame.getAttribute('src')).toContain('var-asset=Line1');
  });

  it('says what to check when the frame fails to load', () => {
    render(<GrafanaEmbed uid="uns-platform-observability" theme="light" title="Platform Observability" />);
    fireEvent.error(screen.getByTitle('Platform Observability'));
    expect(screen.getByText(/could not load/i)).toBeInTheDocument();
    expect(screen.getByText(/uns_grafana/)).toBeInTheDocument();
  });

  it('reports a bad deep link instead of rendering a misleading dashboard', () => {
    render(
      <GrafanaEmbed uid="uns-platform-observability" variables={{ asset: 'Line1' }} theme="dark" title="Broken" />,
    );
    expect(screen.getByText(/does not define var-asset/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Rewrite `GrafanaEmbed.tsx`**

Replace the whole body of the existing file. `GRAFANA_DASHBOARDS`, `GrafanaDashboardId` and `grafanaKioskPath` leave this module — `dashboards.ts` owns them now — so `system/SystemHealthView.tsx`, which imports all three plus `GrafanaEmbed` from here, must be updated in the same commit or the build breaks:

```tsx
import { GRAFANA_DASHBOARDS, type DashboardUid } from '../../lib/grafana/dashboards';
import { GrafanaEmbed } from '../common/GrafanaEmbed';
```

and its `<GrafanaEmbed uid={active.uid} theme={…} title={active.label} />` call gains nothing — the new props are a superset of the old three. Keep `GRAFANA_DASHBOARDS` shaped as it is (`{ platform, process, oee }` mapping to label and uid) so that switcher keeps working; Task 19 deletes the view, but not in this commit.

The load-failure state matters because ADR-0007 records that a missing nginx proxy entry returns `index.html` with a 200 — the iframe then renders the console inside itself instead of erroring. An explicit failure panel plus a named cause is the difference between a fixable report and a confusing screen.

```tsx
import React, { useState } from 'react';
import { dashboardUrl, type EmbedOptions } from '../../lib/grafana/dashboards';
import { EmptyState } from './EmptyState';

type GrafanaEmbedProps = EmbedOptions & { title: string; className?: string };

export const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({ title, className, ...options }) => {
  const [failed, setFailed] = useState(false);

  let src: string;
  try {
    src = dashboardUrl(options);
  } catch (error) {
    return (
      <EmptyState
        title="Dashboard link is wrong"
        detail={error instanceof Error ? error.message : String(error)}
      />
    );
  }

  if (failed) {
    return (
      <EmptyState
        title="Could not load the dashboard"
        detail={`The console proxies /grafana to the uns_grafana service. Check that uns_grafana is running and that nginx.conf still has its location /grafana block — without it the request falls through to index.html with a 200 (ADR-0007).`}
      />
    );
  }

  return (
    <iframe
      title={title}
      src={src}
      onError={() => setFailed(true)}
      className={`h-full w-full border-0 bg-white dark:bg-[#0B0B0C] ${className ?? ''}`}
    />
  );
};
```

The `onError` handler catches a network-level failure. The 200-plus-`index.html` fall-through does not fire it, which is exactly why the detail text names the cause — a reader seeing the console nested inside the panel has the sentence they need.

- [ ] **Step 6: Run both tests**

```bash
cd 11_frontend && npx vitest run src/lib/grafana src/components/common/GrafanaEmbed.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Confirm the three UIDs against the provisioned dashboards**

```bash
cd /c/Dev/unifiednamespace && grep -h '"uid"' 08_uns_observability/grafana/dashboards/*.json | sort -u
```

Expected: the three UIDs in `VARIABLES` appear. If a UID differs, the dashboard JSON wins — fix `dashboards.ts` and the test, not the dashboard.

- [ ] **Step 8: Confirm the variable names the same way**

```bash
cd /c/Dev/unifiednamespace && python -c "
import glob, json
for path in sorted(glob.glob('08_uns_observability/grafana/dashboards/*.json')):
    with open(path, encoding='utf-8') as handle:
        dash = json.load(handle)
    names = [v['name'] for v in dash.get('templating', {}).get('list', [])]
    print(dash.get('uid'), names)
"
```

Expected: `uns-oee ['asset']`, `uns-process-visualization ['topic', 'metric']`, `uns-platform-observability []` — in whatever order the files sort. Any difference is a bug in this task, not in the dashboards.

- [ ] **Step 9: Commit**

```bash
git add 11_frontend/src/lib/grafana/ 11_frontend/src/components/common/GrafanaEmbed.tsx \
  11_frontend/src/components/common/GrafanaEmbed.test.tsx
git commit -m "feat(frontend): embed Grafana through one component and one URL builder

Kiosk mode, theme and the /grafana sub-path are decided once for the three call
sites. Deep links may only set variables the target dashboard declares - Grafana
ignores unknown ones silently, which reads as a broken filter - so an unknown
variable throws and the panel says which ones exist. The load-failure state
names the ADR-0007 fall-through, because a missing proxy entry returns
index.html with a 200 rather than an error."
```

---

## Task 7: Raise the type scale to a readable floor

Spec section 15 sets a floor of 11px. The module currently has 17 uses of `text-[8px]`, 107 of `text-[9px]` and 254 of `text-[10px]`. The spec names "the 124 uses of 8px and 9px type"; the 254 uses of 10px are also below the floor, so they go too — the rule is the requirement, and the count in the spec was a description of the worst of it, not a limit on the sweep.

This is a mechanical task with a mechanical check. It is deliberately placed before the new surfaces so that nothing written after it inherits the old scale.

**Files:**
- Modify: every file under `11_frontend/src` containing `text-[8px]`, `text-[9px]` or `text-[10px]`
- Test: `11_frontend/src/type-scale.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: an enforced floor. Every task after this one writes `text-[11px]` or larger.

- [ ] **Step 1: Write the failing guard**

Create `11_frontend/src/type-scale.test.ts`. It reads the source tree, so it needs Node's `fs` — that is allowed; it is not a network call.

```ts
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname);

/** Spec section 15: 13px body, 12px dense, 11px labels. Nothing below 11px. */
const BELOW_FLOOR = /text-\[(?:[0-9]|10)px\]/;

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(ts|tsx)$/.test(entry) ? [path] : [];
  });

describe('type scale floor', () => {
  it('has no glyph size below 11px anywhere in src', () => {
    const offenders = walk(SRC)
      .filter((path) => !path.endsWith('type-scale.test.ts'))
      .flatMap((path) =>
        readFileSync(path, 'utf8')
          .split('\n')
          .map((line, index) => ({ path, line: index + 1, text: line }))
          .filter((entry) => BELOW_FLOOR.test(entry.text)),
      )
      .map((entry) => `${entry.path}:${entry.line}`);

    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it and watch it fail with the full list**

```bash
cd 11_frontend && npx vitest run src/type-scale.test.ts
```

Expected: FAIL listing 378 locations. Keep the output — it is the work list.

- [ ] **Step 3: Apply the mapping**

All three sizes below the floor become `text-[11px]`. Nothing is promoted further by this command: raising an 8px badge straight to 13px would change layout in 17 places at once, and this task is about legibility, not redesign. Individual promotions to 12px or 13px happen inside the tasks that rewrite those surfaces.

```bash
cd 11_frontend && grep -rl "text-\[8px\]\|text-\[9px\]\|text-\[10px\]" src \
  | xargs sed -i 's/text-\[8px\]/text-[11px]/g; s/text-\[9px\]/text-[11px]/g; s/text-\[10px\]/text-[11px]/g'
```

- [ ] **Step 4: Run the guard again**

```bash
cd 11_frontend && npx vitest run src/type-scale.test.ts
```

Expected: PASS.

- [ ] **Step 5: Check nothing collapsed**

```bash
cd 11_frontend && npx tsc --noEmit && npm run build
```

Expected: both succeed. `sed` touched only class strings, so a failure here means it hit something inside a template literal that was not a class — inspect and repair by hand.

- [ ] **Step 6: Look at it**

```bash
cd 11_frontend && npm run dev
```

Open the console at 1280px, visit `/plant`, `/alarms`, `/historian`, `/sparkplug`, `/streams`, `/simulator` and `/users`, and look for text that now wraps or overflows its container. Fix each by loosening the container (shorter label, `truncate`, more width), never by lowering the size back. Note in the commit which containers you had to adjust.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src
git commit -m "style(frontend): raise every glyph to an 11px floor

378 uses of 8px, 9px and 10px type sat below the spec's floor. Density belongs
to row heights, borders and padding, not to glyph size - an operator reading a
console at arm's length cannot use 8px. Promotions to 12px and 13px happen in
the tasks that rewrite each surface; this pass only lifts the floor."
```

---

## Task 8: The PLANT canvas and its Asset rail

The default destination. A left rail of authored Assets, a header naming the selection, and a tab strip with the six tabs from spec section 8. This task builds the shell and the rail; each tab arrives in its own task, so all six start as an `EmptyState` naming the task that fills it.

The rail lists **Assets**, not UNS Nodes. That is the point of the asset-canvas decision: an operator picks a line, not a topic. Topic browsing lives at `/namespace`.

**Files:**
- Modify: `11_frontend/src/components/plant/PlantView.tsx` (replaces the Task 1 placeholder)
- Create: `11_frontend/src/components/plant/AssetTreeRail.tsx`
- Create: `11_frontend/src/components/plant/tabs/LiveTab.tsx`, `TrendTab.tsx`, `ShiftOeeTab.tsx`, `StopsTab.tsx`, `AlarmsTab.tsx`, `ModelTab.tsx`
- Test: `11_frontend/src/components/plant/PlantView.test.tsx`

**Interfaces:**

- Consumes: `unsGraphQLClient.getAssets()` from the foundation plan. The shape is fixed by `07_uns_graphql/src/uns_graphql/type/asset.py:36-52` and `queries/asset.py:70-91`, read directly:

  ```ts
  /** Already in the repo as GraphqlAssetNode at src/services/graphql/types.ts:14-26,
   *  matching AssetNode in the schema. An Asset is identified by its path — there is
   *  no id field and no parent pointer, because the path IS the hierarchy. */
  export type GraphqlAssetNode = {
    path: string        // 'Ent/Site/Area/Line1/Cell1/G1' — topic prefix this Asset publishes under
    segment: string     // 'G1' — the single topic segment naming it
    level: string       // 'SITE' | 'LINE' | 'WORK_CELL' | 'MACHINE' | ... — levels may be skipped
    name: string        // authored display name, else the segment
    description?: string | null
    manufacturer?: string | null
    modelNumber?: string | null
    serialNumber?: string | null
    criticality?: string | null
    isActive: boolean
    attributes?: { data: unknown } | null
  }
  ```

  `getAssets(under?, levels?, includeInactive?)` returns the model **as a flat list ordered by path** — its own description in `queries/asset.py:66-68` says it "nests trivially in a client". So the rail makes one call and nests locally; there is no per-expand round trip and `getAssetChildren` is not used here. The document already exists: `ASSET_FIELDS` in `src/services/graphql/queries.ts:24-37` selects every field above.

- Produces:
  ```ts
  // PlantView.tsx
  export type PlantTab = 'live' | 'trend' | 'shift' | 'stops' | 'alarms' | 'model';
  export const PlantView: React.FC;

  // AssetTreeRail.tsx
  export const AssetTreeRail: React.FC<{
    selectedPath: string | null;
    onSelect: (asset: GraphqlAssetNode) => void;
  }>;

  // every tab, identically shaped
  export const LiveTab: React.FC<{ asset: GraphqlAssetNode }>;
  ```
  The tab components all take `{ asset: GraphqlAssetNode }` and nothing else. A tab that needs more derives it from the Asset, so switching tabs never loses or re-fetches the selection.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/plant/PlantView.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAssets = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getAssets: (...args: unknown[]) => getAssets(...args) },
}));

import { PlantView } from './PlantView';

const asset = (path: string, level: string, name: string) => ({
  path, level, name,
  segment: path.split('/').at(-1)!,
  description: null, manufacturer: null, modelNumber: null, serialNumber: null,
  criticality: null, isActive: true, attributes: null,
});

// Flat and path-ordered, exactly as getAssets returns it.
const MODEL = [
  asset('CovestroAG', 'ENTERPRISE', 'Covestro AG'),
  asset('CovestroAG/Dormagen', 'SITE', 'Dormagen'),
  asset('CovestroAG/Dormagen/Production/Line1', 'LINE', 'Line 1'),
];

describe('PlantView', () => {
  beforeEach(() => {
    getAssets.mockReset();
    getAssets.mockResolvedValue(MODEL);
  });

  it('nests the flat Asset list and selects the first root', async () => {
    render(<PlantView />);
    expect(await screen.findByRole('button', { name: 'Covestro AG' })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('plant-selection')).toHaveTextContent('CovestroAG'),
    );
    // Descendants are not rendered until their ancestor is expanded.
    expect(screen.queryByRole('button', { name: 'Line 1' })).not.toBeInTheDocument();
  });

  it('reveals a descendant when its ancestor is expanded, without another request', async () => {
    render(<PlantView />);
    await screen.findByRole('button', { name: 'Covestro AG' });
    expect(getAssets).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: /expand covestro ag/i }));
    await userEvent.click(screen.getByRole('button', { name: /expand dormagen/i }));
    expect(await screen.findByRole('button', { name: 'Line 1' })).toBeInTheDocument();
    expect(getAssets).toHaveBeenCalledTimes(1);
  });

  it('selecting an Asset shows its path in the header', async () => {
    render(<PlantView />);
    await screen.findByRole('button', { name: 'Covestro AG' });
    await userEvent.click(screen.getByRole('button', { name: /expand covestro ag/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Dormagen' }));
    expect(screen.getByTestId('plant-selection')).toHaveTextContent('CovestroAG/Dormagen');
  });

  it('offers the six tabs and opens on Live', async () => {
    render(<PlantView />);
    await screen.findByRole('button', { name: 'Covestro AG' });
    for (const tab of ['Live', 'Trend', 'Shift & OEE', 'Stops', 'Alarms', 'Model']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Live' })).toHaveAttribute('aria-selected', 'true');
  });

  it('keeps the selected Asset when the tab changes', async () => {
    render(<PlantView />);
    await screen.findByRole('button', { name: 'Covestro AG' });
    await userEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('tab', { name: 'Model' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('plant-selection')).toHaveTextContent('CovestroAG');
    expect(getAssets).toHaveBeenCalledTimes(1);
  });

  it('says where Assets are authored when the Asset Model is empty', async () => {
    getAssets.mockResolvedValue([]);
    render(<PlantView />);
    expect(await screen.findByText(/no assets in the model/i)).toBeInTheDocument();
    expect(screen.getByText(/conf\//)).toBeInTheDocument();
  });

  it('never sends a topic wildcard to the Asset Model', async () => {
    render(<PlantView />);
    await screen.findByRole('button', { name: 'Covestro AG' });
    const sent = JSON.stringify(getAssets.mock.calls);
    expect(sent).not.toContain('#');
    expect(sent).not.toContain('spBv1.0');
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/PlantView.test.tsx
```

Expected: FAIL — the Task 1 placeholder renders no rail and no tabs.

- [ ] **Step 3: Write `AssetTreeRail`**

One call, nested locally. `path` is both the identity and the hierarchy: an Asset's parent is the longest other path that is a prefix of it. Asset Levels may be skipped (`type/asset.py:41`), so the parent is *not* found by dropping one segment — `CovestroAG/Dormagen/Production/Line1` is a child of `CovestroAG/Dormagen` when no Asset is authored at `CovestroAG/Dormagen/Production`.

```tsx
import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetNode } from '../../services/graphql/types';
import { EmptyState } from '../common/EmptyState';

interface AssetTreeRailProps {
  selectedPath: string | null;
  onSelect: (asset: GraphqlAssetNode) => void;
}

/**
 * Nest a path-ordered flat list. The parent of an Asset is the closest authored
 * ancestor, not the path minus one segment — Asset Levels may be skipped, so a
 * LINE can hang directly off a SITE.
 */
export function nestByPath(assets: GraphqlAssetNode[]): Map<string | null, GraphqlAssetNode[]> {
  const paths = assets.map((asset) => asset.path);
  const byParent = new Map<string | null, GraphqlAssetNode[]>();

  for (const asset of assets) {
    let parent: string | null = null;
    for (const candidate of paths) {
      if (candidate === asset.path) continue;
      if (!asset.path.startsWith(`${candidate}/`)) continue;
      if (parent === null || candidate.length > parent.length) parent = candidate;
    }
    const siblings = byParent.get(parent) ?? [];
    siblings.push(asset);
    byParent.set(parent, siblings);
  }

  return byParent;
}

export const AssetTreeRail: React.FC<AssetTreeRailProps> = ({ selectedPath, onSelect }) => {
  const [assets, setAssets] = useState<GraphqlAssetNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient
      .getAssets()
      .then((loaded) => {
        if (cancelled) return;
        setAssets(loaded);
        const roots = nestByPath(loaded).get(null) ?? [];
        if (roots.length > 0) onSelect(roots[0]);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
    // Mount only. Re-running this would fight the operator's selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const byParent = useMemo(() => nestByPath(assets ?? []), [assets]);

  if (error) return <EmptyState title="Could not load the Asset Model" detail={error} />;

  if (assets === null) {
    return <p className="px-3 py-2 text-[12px] text-[#64748B]">Loading Assets…</p>;
  }

  if (assets.length === 0) {
    return (
      <EmptyState
        title="No Assets in the model"
        detail="Assets are imported from conf/ by the asset_model_setup service in docker-compose.yml. Until the plant hierarchy is authored there, use Namespace to browse published topics."
      />
    );
  }

  const toggle = (path: string) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const renderRow = (asset: GraphqlAssetNode, depth: number): React.ReactNode => {
    const children = byParent.get(asset.path) ?? [];
    const isOpen = expanded.has(asset.path);
    return (
      <li key={asset.path}>
        <div className="flex items-stretch">
          {children.length > 0 ? (
            <button
              type="button"
              onClick={() => toggle(asset.path)}
              aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${asset.name}`}
              className="flex w-5 shrink-0 items-center justify-center text-[#64748B] hover:text-[#0F172A] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:text-[#F8FAFC]"
              style={{ marginLeft: depth * 10 }}
            >
              {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
          ) : (
            <span className="w-5 shrink-0" style={{ marginLeft: depth * 10 }} />
          )}

          <button
            type="button"
            onClick={() => onSelect(asset)}
            title={`${asset.path} — ${asset.level}`}
            className={`min-w-0 flex-1 truncate px-1.5 py-1 text-left text-[12px] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500 ${
              asset.path === selectedPath
                ? 'bg-amber-100 font-semibold text-[#0F172A] dark:bg-[#FFC107]/15 dark:text-[#F8FAFC]'
                : asset.isActive
                ? 'text-[#334155] hover:bg-[#F1F5F9] dark:text-[#CBD5E1] dark:hover:bg-[#1E293B]/50'
                : 'text-[#94A3B8] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/50'
            }`}
          >
            {asset.name}
          </button>
        </div>
        {isOpen && children.length > 0 && <ul>{children.map((child) => renderRow(child, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <nav aria-label="Assets" className="h-full overflow-auto py-1">
      <ul>{(byParent.get(null) ?? []).map((asset) => renderRow(asset, 0))}</ul>
    </nav>
  );
};
```

The selected row is marked by background and weight, not colour alone, per the visual bar. An inactive Asset is dimmed — `isActive` is authored data, not a guess.

- [ ] **Step 4: Write the six placeholder tabs**

Each is a real file at its final path with its final props, so the task that fills it replaces a body. `tabs/LiveTab.tsx`:

```tsx
import React from 'react';
import type { GraphqlAssetNode } from '../../../services/graphql/types';
import { EmptyState } from '../../common/EmptyState';

export const LiveTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => (
  <EmptyState
    title="Live values not built yet"
    detail={`Task 9 of the surfaces plan renders the current Metrics of ${asset.name} here.`}
  />
);
```

Write the other five the same way, changing only the component name, the title and the task number: `ModelTab` (Task 9), `LiveTab` (Task 10), `TrendTab` (Task 11), `ShiftOeeTab` (Task 12), `StopsTab` (Task 13), `AlarmsTab` (Task 14).

- [ ] **Step 5: Write `PlantView`**

```tsx
import React, { useState } from 'react';
import type { GraphqlAssetNode } from '../../services/graphql/types';
import { AssetTreeRail } from './AssetTreeRail';
import { EmptyState } from '../common/EmptyState';
import { LiveTab } from './tabs/LiveTab';
import { TrendTab } from './tabs/TrendTab';
import { ShiftOeeTab } from './tabs/ShiftOeeTab';
import { StopsTab } from './tabs/StopsTab';
import { AlarmsTab } from './tabs/AlarmsTab';
import { ModelTab } from './tabs/ModelTab';

export type PlantTab = 'live' | 'trend' | 'shift' | 'stops' | 'alarms' | 'model';

const TABS: { id: PlantTab; label: string; Body: React.FC<{ asset: GraphqlAssetNode }> }[] = [
  { id: 'live', label: 'Live', Body: LiveTab },
  { id: 'trend', label: 'Trend', Body: TrendTab },
  { id: 'shift', label: 'Shift & OEE', Body: ShiftOeeTab },
  { id: 'stops', label: 'Stops', Body: StopsTab },
  { id: 'alarms', label: 'Alarms', Body: AlarmsTab },
  { id: 'model', label: 'Model', Body: ModelTab },
];

export const PlantView: React.FC = () => {
  const [asset, setAsset] = useState<GraphqlAssetNode | null>(null);
  const [tab, setTab] = useState<PlantTab>('live');
  const active = TABS.find((candidate) => candidate.id === tab)!;

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-64 shrink-0 flex-col border-r border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="border-b border-[#E2E8F0] px-3 py-1.5 text-[11px] font-bold uppercase tracking-widest text-[#64748B] dark:border-[#1E293B]">
          Assets
        </div>
        <AssetTreeRail selectedPath={asset?.path ?? null} onSelect={setAsset} />
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-[#E2E8F0] px-4 pt-2 dark:border-[#1E293B]">
          <div className="flex items-baseline gap-2">
            <h1 className="text-[13px] font-semibold text-[#0F172A] dark:text-[#E2E8F0]">
              {asset?.name ?? 'Plant'}
            </h1>
            <span
              data-testid="plant-selection"
              className="truncate font-mono text-[11px] text-[#64748B]"
              title={asset?.path}
            >
              {asset?.path ?? ''}
            </span>
            {asset && (
              <span className="shrink-0 text-[11px] uppercase tracking-wider text-[#94A3B8]">
                {asset.level}
              </span>
            )}
          </div>

          <div role="tablist" aria-label="Plant views" className="-mb-px flex gap-1 pt-2">
            {TABS.map((candidate) => (
              <button
                key={candidate.id}
                role="tab"
                type="button"
                aria-selected={candidate.id === tab}
                onClick={() => setTab(candidate.id)}
                className={`border-b-2 px-3 py-1.5 text-[13px] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                  candidate.id === tab
                    ? 'border-amber-500 font-semibold text-[#0F172A] dark:border-[#FFC107] dark:text-[#F8FAFC]'
                    : 'border-transparent text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
                }`}
              >
                {candidate.label}
              </button>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {asset ? (
            <active.Body asset={asset} />
          ) : (
            <EmptyState
              title="Pick an Asset"
              detail="Choose a line or a machine on the left to see what it is doing."
            />
          )}
        </div>
      </section>
    </div>
  );
};
```

Switching tabs unmounts the previous body. That is intended: a Trend tab left mounted keeps a subscription open behind a tab nobody is reading.

- [ ] **Step 6: Run the test and the type check**

```bash
cd 11_frontend && npx vitest run src/components/plant/PlantView.test.tsx && npx tsc --noEmit
```

Expected: PASS. If the foundation plan re-exported `GraphqlAssetNode` under another name, import it from wherever it actually lives and correct the import lines above — the field names are fixed by the schema, the type's name is not.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/components/plant/
git commit -m "feat(frontend): add the PLANT canvas and its Asset rail

The default destination now opens on an Asset, not a topic - an operator picks a
line and every tab answers a question about that line. getAssets returns a
path-ordered flat list, so the rail nests it locally in one request; parents are
found by longest-prefix because Asset Levels may be skipped. The six tabs are
shells until their own tasks land."
```

---

## Task 9: PLANT ▸ Model — what the Asset Model says about this Asset

The tab that answers "is this line actually modelled, and in what units?". It shows the authored facts already carried by the selection, plus the Metric Definitions that apply to it. This is where Enrichment becomes visible, and it is the honest place for an integrator to see that a line has no definitions at all.

`getTopicContext(asset.path)` is the one call. Passing an Asset's own path makes `metricPath` empty, and `metric_definitions_for(asset_id, "")` (`09_uns_model/src/uns_model/repositories.py:358-377`) then returns every definition that could apply to that Asset — plant-wide ones first, Asset-specific ones last, "so the later write wins for a shared key" (`asset_context.py:191`).

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts:39-45` (two more fields on `METRIC_DEFINITION_FIELDS`)
- Modify: `11_frontend/src/services/graphql/types.ts:28-35` (the same two fields)
- Modify: `11_frontend/src/services/graphql/client.ts` (add `getTopicContext`, beside `getTopicEnrichment` at `:277-289`)
- Modify: `11_frontend/src/components/plant/tabs/ModelTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/ModelTab.test.tsx`

**Interfaces:**
- Consumes: `GraphqlTopicContext` (`src/services/graphql/types.ts:38-51`), `GET_TOPIC_CONTEXT_QUERY` (`queries.ts:84-105`), `DataTable`, `ValueWithUnit`, `StatusPill`, `EmptyState`.
- Produces:
  ```ts
  // client.ts — the full context object, not the flattened property bag that
  // getTopicEnrichment returns for the payload inspector.
  public async getTopicContext(topic: string): Promise<GraphqlTopicContext | null>;
  ```
  Task 10 (Live) and Task 11 (Trend) both call it.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/plant/tabs/ModelTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getTopicContext = vi.fn();

vi.mock('../../../services/graphql/client', () => ({
  unsGraphQLClient: { getTopicContext: (...args: unknown[]) => getTopicContext(...args) },
}));

import { ModelTab } from './ModelTab';

const LINE1 = {
  path: 'CovestroAG/Dormagen/Production/Line1',
  segment: 'Line1',
  level: 'LINE',
  name: 'Line 1',
  description: 'Polyurethane finishing line',
  manufacturer: 'Krauss-Maffei',
  modelNumber: 'KM-4000',
  serialNumber: null,
  criticality: 'HIGH',
  isActive: true,
  attributes: { data: { costCentre: 'CC-4471' } },
};

const CONTEXT = {
  topic: LINE1.path,
  asset: LINE1,
  metricPath: '',
  enterprise: 'CovestroAG',
  site: 'Dormagen',
  area: null,
  productionUnit: 'Production',
  line: 'Line1',
  workCell: null,
  machine: null,
  metricDefinitions: [
    {
      metricKey: 'ProcessValue/Temperature/value',
      displayName: 'Reactor temperature',
      unitOfMeasure: '°C',
      decimals: 1,
      minValue: 0,
      maxValue: 200,
      deadband: null,
    },
    {
      metricKey: 'ProcessValue/Pressure/value',
      displayName: null,
      unitOfMeasure: null,
      decimals: null,
      minValue: null,
      maxValue: null,
      deadband: null,
    },
  ],
};

describe('ModelTab', () => {
  beforeEach(() => {
    getTopicContext.mockReset();
    getTopicContext.mockResolvedValue(CONTEXT);
  });

  it('asks for the Asset by its own path', async () => {
    render(<ModelTab asset={LINE1} />);
    await screen.findByText('Reactor temperature');
    expect(getTopicContext).toHaveBeenCalledWith(LINE1.path);
  });

  it('shows the authored equipment facts', async () => {
    render(<ModelTab asset={LINE1} />);
    expect(await screen.findByText('Krauss-Maffei')).toBeInTheDocument();
    expect(screen.getByText('KM-4000')).toBeInTheDocument();
    expect(screen.getByText('HIGH')).toBeInTheDocument();
    expect(screen.getByText('Polyurethane finishing line')).toBeInTheDocument();
  });

  it('renders an em dash for a fact that was not authored, never a blank cell', async () => {
    render(<ModelTab asset={LINE1} />);
    const serial = await screen.findByTestId('asset-fact-serialNumber');
    expect(serial).toHaveTextContent('—');
  });

  it('shows the Asset Levels this branch uses and omits the ones it skips', async () => {
    render(<ModelTab asset={LINE1} />);
    expect(await screen.findByText('CovestroAG')).toBeInTheDocument();
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.queryByText(/work cell/i)).not.toBeInTheDocument();
  });

  it('lists a defined Metric with its display name and Unit of Measure', async () => {
    render(<ModelTab asset={LINE1} />);
    expect(await screen.findByText('Reactor temperature')).toBeInTheDocument();
    expect(screen.getByText('°C')).toBeInTheDocument();
    expect(screen.getByText('ProcessValue/Temperature/value')).toBeInTheDocument();
  });

  it('marks a Metric Key with no display name or unit as unenriched', async () => {
    render(<ModelTab asset={LINE1} />);
    await screen.findByText('Reactor temperature');
    const row = screen.getByText('ProcessValue/Pressure/value').closest('tr')!;
    expect(row.textContent).toMatch(/unenriched/i);
  });

  it('names the file to edit when the Asset has no Metric Definitions', async () => {
    getTopicContext.mockResolvedValue({ ...CONTEXT, metricDefinitions: [] });
    render(<ModelTab asset={LINE1} />);
    expect(await screen.findByText(/no metric definitions/i)).toBeInTheDocument();
    expect(screen.getByText(/conf\//)).toBeInTheDocument();
  });

  it('says the Asset is unmodelled when the context is null', async () => {
    getTopicContext.mockResolvedValue(null);
    render(<ModelTab asset={LINE1} />);
    expect(await screen.findByText(/not in the asset model/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/ModelTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 3: Add the two missing fields to the shared fragment**

`decimals` and `deadband` are on `MetricDefinitionType` (`07_uns_graphql/src/uns_graphql/type/asset.py:70-77`) but the document does not select them. Add them — this selects existing schema fields, it does not add any.

In `queries.ts`, `METRIC_DEFINITION_FIELDS` becomes:

```ts
const METRIC_DEFINITION_FIELDS = `
  metricKey
  displayName
  unitOfMeasure
  decimals
  minValue
  maxValue
  deadband
`
```

In `types.ts`, `GraphqlMetricDefinition` becomes:

```ts
/** What the Asset Model says about one Metric Key: its name, its unit, and the range
 *  and rounding an operator should read it at. */
export type GraphqlMetricDefinition = {
  metricKey: string
  displayName?: string | null
  unitOfMeasure?: string | null
  decimals?: number | null
  minValue?: number | null
  maxValue?: number | null
  deadband?: number | null
}
```

`GET_UNS_TREE_CHILDREN_QUERY` interpolates the same constant, so the tree expansion query gains the two fields as well. That is harmless — `metricChildNodes` ignores what it does not read.

- [ ] **Step 4: Add `getTopicContext` to the client**

Beside `getTopicEnrichment` in `client.ts`:

```ts
  /**
   * The whole Enrichment record for one topic: the Asset that publishes it, its name at
   * every Asset Level, and every Metric Definition that applies.
   *
   * Pass an Asset's own path to get that Asset's full definition set — the resolver
   * makes metricPath empty and returns plant-wide definitions plus Asset-specific ones.
   * Null means the topic matches no Asset: an Unmodelled Topic.
   */
  public async getTopicContext(topic: string): Promise<GraphqlTopicContext | null> {
    const res = await this.executeQuery<{ getTopicContext: GraphqlTopicContext | null }>(
      GET_TOPIC_CONTEXT_QUERY,
      { topic },
    )
    if (res.error) throw new Error(res.error)
    return res.data?.getTopicContext ?? null
  }
```

Match the surrounding error convention: if the neighbouring methods swallow `res.error` and return a default, do that instead, and say which you followed in the commit. Do not introduce a second convention in one file.

- [ ] **Step 5: Write `ModelTab`**

```tsx
import React, { useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../../services/graphql/client';
import type { GraphqlAssetNode, GraphqlTopicContext } from '../../../services/graphql/types';
import { DataTable, type Column } from '../../common/DataTable';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill } from '../../common/StatusPill';
import { NO_VALUE } from '../../../lib/oee/format';

type Definition = GraphqlTopicContext['metricDefinitions'][number];

const FACTS: { key: keyof GraphqlAssetNode; label: string }[] = [
  { key: 'level', label: 'Asset Level' },
  { key: 'description', label: 'Description' },
  { key: 'manufacturer', label: 'Manufacturer' },
  { key: 'modelNumber', label: 'Model' },
  { key: 'serialNumber', label: 'Serial' },
  { key: 'criticality', label: 'Criticality' },
];

const LEVELS: { key: keyof GraphqlTopicContext; label: string }[] = [
  { key: 'enterprise', label: 'Enterprise' },
  { key: 'site', label: 'Site' },
  { key: 'area', label: 'Area' },
  { key: 'productionUnit', label: 'Production Unit' },
  { key: 'line', label: 'Line' },
  { key: 'workCell', label: 'Work Cell' },
  { key: 'machine', label: 'Machine' },
];

const COLUMNS: Column<Definition>[] = [
  {
    key: 'metricKey', header: 'Metric Key', mono: true,
    render: (definition) => definition.metricKey,
  },
  {
    key: 'displayName', header: 'Name',
    render: (definition) =>
      definition.displayName ?? (
        <span className="text-[#94A3B8]" title="No display name or Unit of Measure authored">
          Unenriched
        </span>
      ),
  },
  {
    key: 'unitOfMeasure', header: 'Unit', align: 'right',
    render: (definition) => definition.unitOfMeasure ?? NO_VALUE,
  },
  {
    key: 'decimals', header: 'Decimals', align: 'right',
    render: (definition) => definition.decimals ?? NO_VALUE,
  },
  {
    key: 'range', header: 'Range', align: 'right',
    render: (definition) =>
      definition.minValue === null || definition.minValue === undefined ||
      definition.maxValue === null || definition.maxValue === undefined
        ? NO_VALUE
        : `${definition.minValue} … ${definition.maxValue}`,
  },
];

export const ModelTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const [context, setContext] = useState<GraphqlTopicContext | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setContext(undefined);
    setError(null);
    unsGraphQLClient
      .getTopicContext(asset.path)
      .then((loaded) => {
        if (!cancelled) setContext(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [asset.path]);

  if (error) return <EmptyState title="Could not read the Asset Model" detail={error} />;
  if (context === undefined) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading the Asset Model…</p>;
  }
  if (context === null) {
    return (
      <EmptyState
        title="This path is not in the Asset Model"
        detail={`Nothing is authored at ${asset.path}. It is an Unmodelled Topic — Assets and Metric Definitions are imported from conf/ by the asset_model_setup service.`}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4">
      <section>
        <h2 className="pb-1 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">Equipment</h2>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] xl:grid-cols-3">
          {FACTS.map((fact) => {
            const value = asset[fact.key];
            return (
              <div key={fact.key} className="flex justify-between gap-2 border-b border-[#F1F5F9] py-0.5 dark:border-[#1E293B]/60">
                <dt className="shrink-0 text-[#64748B]">{fact.label}</dt>
                <dd
                  data-testid={`asset-fact-${fact.key}`}
                  className={`truncate text-right ${value ? 'text-[#334155] dark:text-[#CBD5E1]' : 'text-[#94A3B8]'}`}
                >
                  {value === null || value === undefined || value === '' ? NO_VALUE : String(value)}
                </dd>
              </div>
            );
          })}
          {!asset.isActive && (
            <div className="col-span-full pt-1">
              <StatusPill label="Inactive" tone="neutral" title="isActive is false in the Asset Model" />
            </div>
          )}
        </dl>
      </section>

      <section>
        <h2 className="pb-1 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">Asset Levels</h2>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          {LEVELS.filter((level) => context[level.key]).map((level) => (
            <span key={level.key} className="text-[#334155] dark:text-[#CBD5E1]">
              <span className="text-[#64748B]">{level.label}: </span>
              {String(context[level.key])}
            </span>
          ))}
        </div>
      </section>

      <section className="flex min-h-0 flex-1 flex-col">
        <h2 className="pb-1 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
          Metric Definitions ({context.metricDefinitions.length})
        </h2>
        <DataTable
          columns={COLUMNS}
          rows={context.metricDefinitions}
          rowKey={(definition) => definition.metricKey}
          empty={
            <EmptyState
              title="No Metric Definitions for this Asset"
              detail="Live values will show raw numbers with no unit until definitions are authored in conf/ and imported by asset_model_setup."
            />
          }
        />
      </section>
    </div>
  );
};
```

Levels the branch skips render nothing at all, because `TopicContextType` returns null for them (`type/asset.py:99-107`) and an empty `Work Cell:` label would imply an unnamed work cell exists.

- [ ] **Step 6: Run the test**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/ModelTab.test.tsx && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 7: Regenerate nothing, but check the document still parses**

```bash
cd 11_frontend && npx vitest run src/services
```

Expected: PASS — the foundation plan's client tests still hold with the two extra fields selected.

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/services/graphql/ 11_frontend/src/components/plant/tabs/ModelTab.tsx \
  11_frontend/src/components/plant/tabs/ModelTab.test.tsx
git commit -m "feat(frontend): show what the Asset Model says about the selected Asset

PLANT > Model answers 'is this line modelled, and in what units'. One
getTopicContext call on the Asset's own path returns every Metric Definition
that applies, because an empty metric path matches all of them. Unauthored facts
render an em dash and a Metric Key with no name or unit is labelled unenriched -
an integrator can see the gap instead of guessing at it. decimals and deadband
were already in the schema and are now selected."
```

---

## Task 10: PLANT ▸ Live — the current value of every Metric under this Asset

The tab an operator opens first. It answers "what is this line doing right now" from the graph of current state, then keeps itself current from the MQTT subscription. It is also the surface where Enrichment pays off or visibly does not: a Metric with a Metric Definition shows a name and a Unit of Measure, and one without shows the raw payload leaf and is labelled `Unenriched`.

Three facts from the repo shape this task, and none of them may be re-derived by guessing:

1. **A Metric Key is a path, not a payload key.** `12_uns_oee/src/uns_oee/sources.py:92-102` resolves a binding by splitting on the last separator: everything before it is appended to the Asset path to make a topic, and the last segment is the payload leaf. `Cell1/MES-01/Status/PackMlState/value` on Asset `A` means topic `A/Cell1/MES-01/Status/PackMlState`, payload key `value`. The reverse of that split is how this tab labels a value.
2. **`getUnsNodes` accepts wildcards.** `07_uns_graphql/src/uns_graphql/queries/graph.py:157-185` compiles `#` into `PARENT_OF*1..10` and `+` into a single hop. One request with `{asset.path}/#` returns the current state of the whole subtree. The tree constraint in Global Constraints bans `#` in *tree expansion*, where it would replace lazy loading; this is a bounded single-Asset read, and `historianTopic()` in `src/lib/uns/topics.ts:11-13` already uses the same pattern for the same reason.
3. **Staleness is already an operator setting.** `settings.staleThresholdMinutes` (default 5, `src/types/uns.ts:133`, edited in the health view) with `isNodeStale()` and `formatAge()` from `src/lib/uns/node-meta.ts:84-98`. Do not invent a second threshold.

**Files:**
- Create: `11_frontend/src/lib/plant/metric-rows.ts`
- Test: `11_frontend/src/lib/plant/metric-rows.test.ts`
- Modify: `11_frontend/src/lib/uns/topics.ts` (add `subtreeTopic`, make `historianTopic` delegate)
- Modify: `11_frontend/src/components/plant/tabs/LiveTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/LiveTab.test.tsx`

**Interfaces:**
- Consumes: `unsGraphQLClient.getUnsNodes(topics: string[]): Promise<UnsNode[]>` (`client.ts:190`), `unsGraphQLClient.subscribeMqttMessages(topics: string[], onMessage): () => void` (`client.ts:512`), `getTopicContext` (Task 9), `useUNS().settings`, `ValueWithUnit`, `StatusPill`, `DataTable`, `EmptyState`, `formatAge`, `isNodeStale`, `NO_VALUE`.
- Produces:
  ```ts
  // src/lib/uns/topics.ts
  /** Every topic below this one, at any depth. Not for tree expansion — see childrenTopic. */
  export function subtreeTopic(namespace: string): string;

  // src/lib/plant/metric-rows.ts
  export interface MetricRow {
    topic: string;
    metricName: string;
    metricKey: string;
    value: string | number | boolean | null;
    lastUpdated: string;
    definition?: GraphqlMetricDefinition;
  }
  export interface MetricRowResult {
    rows: MetricRow[];
    totalRows: number;
    hiddenComplexValues: number;
    binaryTopics: string[];
  }
  export function metricRows(
    assetPath: string,
    nodes: Pick<UnsNode, 'topic' | 'payload' | 'lastUpdated'>[],
    definitions: GraphqlMetricDefinition[],
    limit: number,
  ): MetricRowResult;
  export const MAX_LIVE_ROWS = 300;
  ```
  Task 11 (Trend) imports `MetricRow` to name the series an operator picked.

- [ ] **Step 1: Write the failing test for the pure function**

Create `11_frontend/src/lib/plant/metric-rows.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { metricRows } from './metric-rows';

const ASSET = 'CovestroAG/Dormagen/Packaging/PackLine1';

const NODES = [
  {
    topic: `${ASSET}/Cell1/MES-01/Status/PackMlState`,
    payload: { value: 3, timestamp: 1_756_000_000_000 },
    lastUpdated: '2026-09-02T10:00:00.000Z',
  },
  {
    topic: `${ASSET}/Cell1/MES-01/ProcessValue/GoodCount`,
    payload: { value: 1420 },
    lastUpdated: '2026-09-02T10:00:01.000Z',
  },
];

const DEFINITIONS = [
  {
    metricKey: 'Cell1/MES-01/ProcessValue/GoodCount/value',
    displayName: 'Good count',
    unitOfMeasure: 'ea',
    decimals: 0,
    minValue: 0,
    maxValue: null,
    deadband: null,
  },
];

describe('metricRows', () => {
  it('rebuilds the Metric Key the Asset Model uses, path then payload leaf', () => {
    const { rows } = metricRows(ASSET, NODES, DEFINITIONS, 100);
    expect(rows.map((row) => row.metricKey)).toContain('Cell1/MES-01/Status/PackMlState/value');
  });

  it('joins a row to its Metric Definition by exact Metric Key', () => {
    const { rows } = metricRows(ASSET, NODES, DEFINITIONS, 100);
    const good = rows.find((row) => row.metricName === 'value' && row.topic.endsWith('GoodCount'))!;
    expect(good.definition?.displayName).toBe('Good count');
    const state = rows.find((row) => row.topic.endsWith('PackMlState') && row.metricName === 'value')!;
    expect(state.definition).toBeUndefined();
  });

  it('lets an Asset-specific definition win over a plant-wide one for the same key', () => {
    // The resolver returns plant-wide definitions first and Asset-specific ones last,
    // and callers keep the last match (09_uns_model/src/uns_model/repositories.py:358-377).
    const { rows } = metricRows(ASSET, NODES, [
      { ...DEFINITIONS[0], displayName: 'Plant-wide good count', unitOfMeasure: 'pcs' },
      DEFINITIONS[0],
    ], 100);
    const good = rows.find((row) => row.topic.endsWith('GoodCount'))!;
    expect(good.definition?.unitOfMeasure).toBe('ea');
  });

  it('makes one row per payload leaf, so timestamp is a row too', () => {
    const { rows } = metricRows(ASSET, NODES, DEFINITIONS, 100);
    expect(rows.filter((row) => row.topic.endsWith('PackMlState'))).toHaveLength(2);
  });

  it('orders rows by Metric Key so a live feed cannot reshuffle the table', () => {
    const { rows } = metricRows(ASSET, NODES, DEFINITIONS, 100);
    expect(rows.map((row) => row.metricKey)).toEqual([...rows.map((row) => row.metricKey)].sort());
  });

  it('counts nested attributes instead of dropping them silently', () => {
    const { rows, hiddenComplexValues } = metricRows(
      ASSET,
      [{ topic: `${ASSET}/A/B`, payload: { value: 1, limits: { high: 9 } }, lastUpdated: '2026-09-02T10:00:00.000Z' }],
      [],
      100,
    );
    expect(rows).toHaveLength(1);
    expect(hiddenComplexValues).toBe(1);
  });

  it('reports a non-JSON payload as a binary topic and never decodes it', () => {
    const { rows, binaryTopics } = metricRows(
      ASSET,
      [{ topic: `${ASSET}/A/B`, payload: 'CgkIARIFdmFsdWU=', lastUpdated: '2026-09-02T10:00:00.000Z' }],
      [],
      100,
    );
    expect(rows).toHaveLength(0);
    expect(binaryTopics).toEqual([`${ASSET}/A/B`]);
  });

  it('ignores a node that is not below the Asset', () => {
    const { rows } = metricRows(
      ASSET,
      [{ topic: 'CovestroAG/Dormagen/Packaging/PackLine2/A/B', payload: { value: 1 }, lastUpdated: '2026-09-02T10:00:00.000Z' }],
      [],
      100,
    );
    expect(rows).toHaveLength(0);
  });

  it('ignores the Asset topic itself, which has no Metric Key', () => {
    const { rows } = metricRows(
      ASSET,
      [{ topic: ASSET, payload: { value: 1 }, lastUpdated: '2026-09-02T10:00:00.000Z' }],
      [],
      100,
    );
    expect(rows).toHaveLength(0);
  });

  it('caps the rows it returns and reports the true total', () => {
    const many = Array.from({ length: 40 }, (_, index) => ({
      topic: `${ASSET}/A/M${String(index).padStart(3, '0')}`,
      payload: { value: index },
      lastUpdated: '2026-09-02T10:00:00.000Z',
    }));
    const { rows, totalRows } = metricRows(ASSET, many, [], 10);
    expect(rows).toHaveLength(10);
    expect(totalRows).toBe(40);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/plant/metric-rows.test.ts
```

Expected: FAIL — `Failed to resolve import "./metric-rows"`.

- [ ] **Step 3: Write the pure function**

Create `11_frontend/src/lib/plant/metric-rows.ts`:

```ts
import type { UnsNode } from '../../types/uns'
import type { GraphqlMetricDefinition } from '../../services/graphql/types'

/**
 * One current value: where it was published, what the payload called it, and what the
 * Asset Model says it is.
 */
export interface MetricRow {
  /** Full MQTT topic. */
  topic: string
  /** The payload key the value sits under. */
  metricName: string
  /** As the Asset Model spells it: the segments below the Asset, then the payload leaf. */
  metricKey: string
  value: string | number | boolean | null
  lastUpdated: string
  /** Absent means this Metric has no Metric Definition: unenriched. */
  definition?: GraphqlMetricDefinition
}

export interface MetricRowResult {
  /** At most `limit` rows, in Metric Key order. */
  rows: MetricRow[]
  /** How many rows existed before the cap, so the cap can be disclosed. */
  totalRows: number
  /** Payload entries that were objects or arrays rather than readings. */
  hiddenComplexValues: number
  /** Topics whose payload was not a JSON object. Never decoded here. */
  binaryTopics: string[]
}

/** The most rows one Asset's Live tab will render. Above this, narrow the selection. */
export const MAX_LIVE_ROWS = 300

function isReading(value: unknown): value is string | number | boolean | null {
  return value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

/**
 * Current values under one Asset, joined to the Asset Model.
 *
 * The Metric Key is rebuilt by inverting split_metric_key
 * (12_uns_oee/src/uns_oee/sources.py:92-102): the topic below the Asset, then the
 * payload leaf. That is the only spelling that matches a Metric Definition row.
 */
export function metricRows(
  assetPath: string,
  nodes: Pick<UnsNode, 'topic' | 'payload' | 'lastUpdated'>[],
  definitions: GraphqlMetricDefinition[],
  limit: number,
): MetricRowResult {
  // Built in the order the resolver returned them, so an Asset-specific definition
  // overwrites the plant-wide one for the same key.
  const byKey = new Map<string, GraphqlMetricDefinition>()
  for (const definition of definitions) {
    byKey.set(definition.metricKey, definition)
  }

  const prefix = `${assetPath}/`
  const rows: MetricRow[] = []
  const binaryTopics: string[] = []
  let hiddenComplexValues = 0

  for (const node of nodes) {
    if (!node.topic.startsWith(prefix)) {
      // Either a sibling branch or the Asset's own topic, which has no Metric Key.
      continue
    }
    const below = node.topic.slice(prefix.length)
    const payload = node.payload
    if (payload === null || payload === undefined || typeof payload !== 'object' || Array.isArray(payload)) {
      // Not a JSON object: a bare scalar or Sparkplug bytes. Reported, never decoded.
      binaryTopics.push(node.topic)
      continue
    }
    for (const [metricName, value] of Object.entries(payload)) {
      if (!isReading(value)) {
        hiddenComplexValues += 1
        continue
      }
      const metricKey = `${below}/${metricName}`
      rows.push({
        topic: node.topic,
        metricName,
        metricKey,
        value,
        lastUpdated: node.lastUpdated,
        definition: byKey.get(metricKey),
      })
    }
  }

  rows.sort((left, right) => left.metricKey.localeCompare(right.metricKey))
  return {
    rows: rows.slice(0, limit),
    totalRows: rows.length,
    hiddenComplexValues,
    binaryTopics: [...new Set(binaryTopics)].sort(),
  }
}
```

- [ ] **Step 4: Add `subtreeTopic` and run the pure tests**

In `src/lib/uns/topics.ts`, replace `historianTopic` with:

```ts
/**
 * Every topic below this one, at any depth. `getUnsNodes` compiles `#` into
 * PARENT_OF*1..10, so this is one request for a whole subtree's current state.
 *
 * Not for tree expansion — that uses childrenTopic() so a node loads one level at a
 * time. Use this only for a bounded read under one selected node.
 */
export function subtreeTopic(namespace: string): string {
  return `${namespace}/#`
}

/** @deprecated Use subtreeTopic. Kept because existing callers read better this way. */
export function historianTopic(namespace: string): string {
  return subtreeTopic(namespace)
}
```

```bash
cd 11_frontend && npx vitest run src/lib/plant/metric-rows.test.ts && npx tsc --noEmit
```

Expected: PASS, 11 tests.

- [ ] **Step 5: Write the failing component test**

Create `11_frontend/src/components/plant/tabs/LiveTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MqttMessage } from '../../../types/uns';

const getUnsNodes = vi.fn();
const getTopicContext = vi.fn();
const subscribeMqttMessages = vi.fn();
let emit: ((msg: MqttMessage) => void) | undefined;

vi.mock('../../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getUnsNodes: (...args: unknown[]) => getUnsNodes(...args),
    getTopicContext: (...args: unknown[]) => getTopicContext(...args),
    subscribeMqttMessages: (topics: string[], onMessage: (msg: MqttMessage) => void) => {
      emit = onMessage;
      return subscribeMqttMessages(topics, onMessage);
    },
  },
}));

vi.mock('../../../context/UNSContext', () => ({
  useUNS: () => ({ settings: { staleThresholdMinutes: 5 } }),
}));

import { LiveTab } from './LiveTab';

const ASSET = {
  path: 'CovestroAG/Dormagen/Packaging/PackLine1',
  segment: 'PackLine1',
  level: 'LINE',
  name: 'Pack Line 1',
  isActive: true,
};

const NOW = new Date('2026-09-02T10:00:00.000Z');

const NODES = [
  {
    topic: `${ASSET.path}/Cell1/MES-01/ProcessValue/GoodCount`,
    payload: { value: 1420.4 },
    lastUpdated: NOW.toISOString(),
  },
  {
    topic: `${ASSET.path}/Cell1/MES-01/Status/PackMlState`,
    payload: { value: 3 },
    lastUpdated: NOW.toISOString(),
  },
];

const CONTEXT = {
  topic: ASSET.path,
  asset: ASSET,
  metricPath: '',
  metricDefinitions: [
    {
      metricKey: 'Cell1/MES-01/ProcessValue/GoodCount/value',
      displayName: 'Good count',
      unitOfMeasure: 'ea',
      decimals: 1,
      minValue: 0,
      maxValue: null,
      deadband: null,
    },
  ],
};

describe('LiveTab', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    emit = undefined;
    getUnsNodes.mockReset().mockResolvedValue(NODES);
    getTopicContext.mockReset().mockResolvedValue(CONTEXT);
    subscribeMqttMessages.mockReset().mockReturnValue(() => undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads the whole subtree in one request', async () => {
    render(<LiveTab asset={ASSET} />);
    await screen.findByText('Good count');
    expect(getUnsNodes).toHaveBeenCalledTimes(1);
    expect(getUnsNodes).toHaveBeenCalledWith([`${ASSET.path}/#`]);
  });

  // Spec test 12.
  it('shows a defined Metric with its display name and Unit of Measure', async () => {
    render(<LiveTab asset={ASSET} />);
    expect(await screen.findByText('Good count')).toBeInTheDocument();
    const row = screen.getByText('Good count').closest('tr')!;
    expect(row.textContent).toContain('1420.4');
    expect(row.textContent).toContain('ea');
    expect(row.textContent).not.toMatch(/unenriched/i);
  });

  // Spec test 12, the other half.
  it('shows an undefined Metric raw and labels it unenriched', async () => {
    render(<LiveTab asset={ASSET} />);
    await screen.findByText('Good count');
    const row = screen.getByText('Cell1/MES-01/Status/PackMlState/value').closest('tr')!;
    expect(row.textContent).toContain('3');
    expect(row.textContent).toMatch(/unenriched/i);
  });

  it('subscribes to the same subtree and updates a value in place', async () => {
    render(<LiveTab asset={ASSET} />);
    await screen.findByText('Good count');
    expect(subscribeMqttMessages).toHaveBeenCalledWith([`${ASSET.path}/#`], expect.any(Function));

    await act(async () => {
      emit!({
        id: 'm1',
        topic: `${ASSET.path}/Cell1/MES-01/ProcessValue/GoodCount`,
        payload: { value: 1421 },
        timestamp: NOW.toISOString(),
      });
      vi.advanceTimersByTime(300);
    });

    const row = screen.getByText('Good count').closest('tr')!;
    expect(row.textContent).toContain('1421.0');
    expect(screen.getAllByText('Good count')).toHaveLength(1);
  });

  it('adds a Metric that only appears on the feed', async () => {
    render(<LiveTab asset={ASSET} />);
    await screen.findByText('Good count');

    await act(async () => {
      emit!({
        id: 'm2',
        topic: `${ASSET.path}/Cell1/MES-01/ProcessValue/RejectCount`,
        payload: { value: 7 },
        timestamp: NOW.toISOString(),
      });
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByText('Cell1/MES-01/ProcessValue/RejectCount/value')).toBeInTheDocument();
  });

  it('marks a row stale when it is older than the operator threshold', async () => {
    getUnsNodes.mockResolvedValue([
      { ...NODES[0], lastUpdated: '2026-09-02T09:00:00.000Z' },
      NODES[1],
    ]);
    render(<LiveTab asset={ASSET} />);
    const row = (await screen.findByText('Good count')).closest('tr')!;
    expect(row.textContent).toMatch(/stale/i);
    expect(row.textContent).toMatch(/1 hr ago/);
  });

  it('names a binary payload without decoding it', async () => {
    getUnsNodes.mockResolvedValue([
      { topic: `${ASSET.path}/Cell1/Raw`, payload: 'CgkIARIFdmFsdWU=', lastUpdated: NOW.toISOString() },
    ]);
    render(<LiveTab asset={ASSET} />);
    expect(await screen.findByText(/not decoded in the browser/i)).toBeInTheDocument();
    expect(screen.getByText(`${ASSET.path}/Cell1/Raw`)).toBeInTheDocument();
    expect(screen.queryByText('CgkIARIFdmFsdWU=')).not.toBeInTheDocument();
    // Not "nothing has been published" — something was, it just is not readable here.
    expect(screen.getByText(/no readable metrics/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing has been published/i)).not.toBeInTheDocument();
  });

  it('says the cap was applied instead of pretending it showed everything', async () => {
    getUnsNodes.mockResolvedValue(
      Array.from({ length: 400 }, (_, index) => ({
        topic: `${ASSET.path}/A/M${String(index).padStart(3, '0')}`,
        payload: { value: index },
        lastUpdated: NOW.toISOString(),
      })),
    );
    render(<LiveTab asset={ASSET} />);
    expect(await screen.findByTestId('live-row-cap')).toHaveTextContent('300');
    expect(screen.getByTestId('live-row-cap')).toHaveTextContent('400');
  });

  it('tells the operator what to do when nothing has been published here', async () => {
    getUnsNodes.mockResolvedValue([]);
    render(<LiveTab asset={ASSET} />);
    expect(await screen.findByText(/nothing has been published/i)).toBeInTheDocument();
  });

  it('drops the subscription when the tab unmounts', async () => {
    const unsubscribe = vi.fn();
    subscribeMqttMessages.mockReturnValue(unsubscribe);
    const { unmount } = render(<LiveTab asset={ASSET} />);
    await screen.findByText('Good count');
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 6: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/LiveTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 7: Write `LiveTab`**

```tsx
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { unsGraphQLClient } from '../../../services/graphql/client';
import { useUNS } from '../../../context/UNSContext';
import type { GraphqlAssetNode, GraphqlMetricDefinition } from '../../../services/graphql/types';
import type { MqttMessage, UnsNode } from '../../../types/uns';
import { subtreeTopic } from '../../../lib/uns/topics';
import { formatAge, isNodeStale } from '../../../lib/uns/node-meta';
import { MAX_LIVE_ROWS, metricRows, type MetricRow } from '../../../lib/plant/metric-rows';
import { DataTable, type Column } from '../../common/DataTable';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill } from '../../common/StatusPill';
import { ValueWithUnit } from '../../common/ValueWithUnit';
import { NO_VALUE } from '../../../lib/oee/format';

/** Current state of one topic, from the graph read or the last message on the feed. */
type NodeState = Pick<UnsNode, 'topic' | 'payload' | 'lastUpdated'>;

/**
 * A busy line publishes faster than a table should re-render. Messages are collected and
 * applied on this cadence, so the feed cannot starve the main thread.
 */
const FLUSH_MS = 250;

function columns(thresholdMinutes: number): Column<MetricRow>[] {
  return [
    {
      key: 'metric',
      header: 'Metric',
      render: (row) => row.definition?.displayName ?? row.metricName,
    },
    {
      key: 'metricKey',
      header: 'Metric Key',
      mono: true,
      render: (row) => row.metricKey,
    },
    {
      key: 'value',
      header: 'Value',
      align: 'right',
      render: (row) => (
        <ValueWithUnit
          value={typeof row.value === 'boolean' ? String(row.value) : row.value}
          unit={row.definition?.unitOfMeasure}
          decimals={row.definition?.decimals ?? undefined}
          unenriched={!row.definition}
        />
      ),
    },
    {
      key: 'range',
      header: 'Range',
      align: 'right',
      render: (row) => {
        const { minValue, maxValue } = row.definition ?? {};
        if (minValue === null || minValue === undefined || maxValue === null || maxValue === undefined) {
          return NO_VALUE;
        }
        return `${minValue} … ${maxValue}`;
      },
    },
    {
      key: 'age',
      header: 'Updated',
      align: 'right',
      render: (row) => formatAge(row.lastUpdated),
    },
    {
      key: 'flags',
      header: '',
      render: (row) => (
        <span className="flex gap-1">
          {!row.definition && (
            <StatusPill
              label="Unenriched"
              tone="neutral"
              title="No Metric Definition for this Metric Key, so its name, unit and range are unknown"
            />
          )}
          {isNodeStale(row.lastUpdated, thresholdMinutes) && (
            <StatusPill
              label="Stale"
              tone="warn"
              title={`No update for more than ${thresholdMinutes} min`}
            />
          )}
        </span>
      ),
    },
  ];
}

export const LiveTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const { settings } = useUNS();
  const thresholdMinutes = settings.staleThresholdMinutes || 5;

  const [nodes, setNodes] = useState<Map<string, NodeState> | null>(null);
  const [definitions, setDefinitions] = useState<GraphqlMetricDefinition[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Messages land here between flushes so a fast feed does not re-render per message.
  const pending = useRef(new Map<string, NodeState>());

  useEffect(() => {
    let cancelled = false;
    const topic = subtreeTopic(asset.path);
    setNodes(null);
    setDefinitions([]);
    setError(null);
    pending.current.clear();

    Promise.all([unsGraphQLClient.getUnsNodes([topic]), unsGraphQLClient.getTopicContext(asset.path)])
      .then(([loaded, context]) => {
        if (cancelled) return;
        setNodes(
          new Map(
            loaded.map((node) => [
              node.topic,
              { topic: node.topic, payload: node.payload, lastUpdated: node.lastUpdated },
            ]),
          ),
        );
        setDefinitions(context?.metricDefinitions ?? []);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });

    const onMessage = (message: MqttMessage) => {
      pending.current.set(message.topic, {
        topic: message.topic,
        payload: message.payload,
        lastUpdated: message.timestamp,
      });
    };
    const unsubscribe = unsGraphQLClient.subscribeMqttMessages([topic], onMessage);

    const flush = window.setInterval(() => {
      if (pending.current.size === 0) return;
      const batch = pending.current;
      pending.current = new Map();
      setNodes((current) => {
        const next = new Map(current ?? []);
        for (const [key, state] of batch) next.set(key, state);
        return next;
      });
    }, FLUSH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(flush);
      unsubscribe();
    };
  }, [asset.path]);

  const result = useMemo(
    () => metricRows(asset.path, [...(nodes?.values() ?? [])], definitions, MAX_LIVE_ROWS),
    [asset.path, nodes, definitions],
  );

  if (error) return <EmptyState title="Could not read current state" detail={error} />;
  if (nodes === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading current state…</p>;
  }

  const capped = result.totalRows - result.rows.length;

  // Two different nothings. Claiming "nothing published" while a binary topic is listed
  // below the table would be the kind of untruth this console exists to remove.
  const empty =
    result.binaryTopics.length > 0 ? (
      <EmptyState
        title="No readable Metrics below this Asset"
        detail="Everything published here has a binary payload, listed below. Decoded Sparkplug values are on the Sparkplug screen."
      />
    ) : (
      <EmptyState
        title="Nothing has been published below this Asset"
        detail="The Asset Model declares it, but no MQTT message has reached the graph yet. Check the Mapper for this line, or select a parent to see where data is arriving."
      />
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1">
        <DataTable
          columns={columns(thresholdMinutes)}
          rows={result.rows}
          rowKey={(row) => `${row.topic}#${row.metricName}`}
          empty={empty}
        />
      </div>

      <div className="shrink-0 space-y-1 border-t border-[#E2E8F0] px-3 py-2 text-[11px] text-[#64748B] dark:border-[#1E293B]">
        {capped > 0 && (
          <p data-testid="live-row-cap">
            Showing {result.rows.length} of {result.totalRows} Metrics in Metric Key order. Select a
            Line, Work Cell or Machine to narrow.
          </p>
        )}
        {result.hiddenComplexValues > 0 && (
          <p>
            {result.hiddenComplexValues} nested attribute
            {result.hiddenComplexValues === 1 ? '' : 's'} are not simple readings and are not listed.
          </p>
        )}
        {result.binaryTopics.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill label="Binary" tone="info" title="Payload is bytes, not JSON" />
            <span>Binary payload, not decoded in the browser:</span>
            {result.binaryTopics.map((topic) => (
              <code key={topic} className="font-mono text-[11px] text-[#94A3B8]">
                {topic}
              </code>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 8: Run the tests**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/LiveTab.test.tsx src/lib/plant && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 9: Check no other caller of the renamed helper broke**

```bash
cd 11_frontend && grep -rn "historianTopic\|subtreeTopic" src && npm run build
```

Expected: existing `historianTopic` call sites still compile; the build succeeds.

- [ ] **Step 10: Commit**

```bash
git add 11_frontend/src/lib/plant/ 11_frontend/src/lib/uns/topics.ts \
  11_frontend/src/components/plant/tabs/LiveTab.tsx \
  11_frontend/src/components/plant/tabs/LiveTab.test.tsx
git commit -m "feat(frontend): current value of every Metric under the selected Asset

One getUnsNodes read of {asset}/# for current state, one subscription on the same
subtree for updates, coalesced every 250ms so a fast line cannot thrash the table.
Rows are keyed by the Metric Key the Asset Model uses - the topic below the Asset
plus the payload leaf, the inverse of split_metric_key - so a definition either
matches exactly or the row is labelled Unenriched. Nothing is dropped quietly: the
row cap, nested attributes and binary payloads are each stated. Binary payloads are
named, never decoded."
```

---

## Task 11: PLANT ▸ Trend — history from the historian, live from the feed

This is the hybrid split, and the repo decides it rather than taste:

- `uns_metrics_1m` is a continuous aggregate with `end_offset => INTERVAL '1 minute'` (`04_uns_historian/sql_scripts/04_setup_metrics_hypertable.sql:49-56`). The newest bucket is deliberately not materialised, so a Grafana trend is always at least a minute behind. That is correct for a trend and wrong for a value an operator is watching — which is why Live reads the graph and subscribes, and Trend embeds a dashboard.
- `uns-process-visualization` panel 1 queries `uns_metrics_1m_enriched` with `topic LIKE '%$topic%' AND metric_name LIKE '%$metric%'`, and both variables are `textbox` type labelled "contains" (`08_uns_observability/grafana/dashboards/process-visualization.json`). Passing an exact topic is a valid substring filter, so a selection narrows to one series and the operator can widen it in Grafana.
- The aggregate is defined `WHERE value_double IS NOT NULL` (`:32`, `:45`). A Metric stored as text — a recipe id, a state name — has history in `uns_metrics.value_text` but is absent from the aggregate the dashboard reads. So a text Metric must be shown as *not chartable here*, with the reason, not as an empty graph.
- The view builds `metric_key` as `metric_path || '/' || metric_name` (`09_uns_model/migrations/versions/0001_asset_model.py:147-150`), the same spelling `metricRows` reconstructs. The Metric Key an operator picks in the console is the Metric Key the historian stores.

The tab also needs the Metric list Live already builds. Rather than issue the same two reads twice, this task first extracts that effect out of `LiveTab` into a hook. The Task 10 tests are the safety net: they must pass unchanged afterwards, without editing a single assertion.

**Files:**
- Create: `11_frontend/src/components/plant/useAssetMetrics.ts`
- Test: `11_frontend/src/components/plant/useAssetMetrics.test.tsx`
- Modify: `11_frontend/src/components/plant/tabs/LiveTab.tsx` (consume the hook; behaviour unchanged)
- Modify: `11_frontend/src/components/plant/tabs/TrendTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/TrendTab.test.tsx`

**Interfaces:**
- Consumes: `metricRows`, `MAX_LIVE_ROWS`, `MetricRow` (Task 10), `subtreeTopic` (Task 10), `GrafanaEmbed`, `EmbedOptions` (Task 6), `useTheme()`, `DataTable`, `EmptyState`, `StatusPill`.
- Produces:
  ```ts
  // src/components/plant/useAssetMetrics.ts
  export interface AssetMetrics {
    /** null while the first read is outstanding. */
    result: MetricRowResult | null;
    error: string | null;
  }
  /**
   * Current state of every Metric under an Asset, joined to the Asset Model.
   * `live: true` also subscribes and coalesces updates; `live: false` reads once.
   */
  export function useAssetMetrics(assetPath: string, options: { live: boolean }): AssetMetrics;
  ```
  Task 12 does not use it — OEE comes from `oeeShiftResults`, not from Metrics.

- [ ] **Step 1: Write the hook test**

Create `11_frontend/src/components/plant/useAssetMetrics.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MqttMessage } from '../../types/uns';

const getUnsNodes = vi.fn();
const getTopicContext = vi.fn();
const subscribeMqttMessages = vi.fn();
let emit: ((msg: MqttMessage) => void) | undefined;

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getUnsNodes: (...args: unknown[]) => getUnsNodes(...args),
    getTopicContext: (...args: unknown[]) => getTopicContext(...args),
    subscribeMqttMessages: (topics: string[], onMessage: (msg: MqttMessage) => void) => {
      emit = onMessage;
      return subscribeMqttMessages(topics, onMessage);
    },
  },
}));

import { useAssetMetrics } from './useAssetMetrics';

const ASSET_PATH = 'CovestroAG/Dormagen/Packaging/PackLine1';
const NOW = new Date('2026-09-02T10:00:00.000Z');

const Probe: React.FC<{ path: string; live: boolean }> = ({ path, live }) => {
  const { result, error } = useAssetMetrics(path, { live });
  if (error) return <p>error: {error}</p>;
  if (!result) return <p>loading</p>;
  return <p data-testid="keys">{result.rows.map((row) => row.metricKey).join(',')}</p>;
};

describe('useAssetMetrics', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    emit = undefined;
    getUnsNodes.mockReset().mockResolvedValue([
      { topic: `${ASSET_PATH}/A/B`, payload: { value: 1 }, lastUpdated: NOW.toISOString() },
    ]);
    getTopicContext.mockReset().mockResolvedValue({ metricDefinitions: [] });
    subscribeMqttMessages.mockReset().mockReturnValue(() => undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads the subtree and the Enrichment once', async () => {
    render(<Probe path={ASSET_PATH} live={false} />);
    expect(await screen.findByTestId('keys')).toHaveTextContent('A/B/value');
    expect(getUnsNodes).toHaveBeenCalledWith([`${ASSET_PATH}/#`]);
    expect(getTopicContext).toHaveBeenCalledWith(ASSET_PATH);
  });

  it('does not subscribe when live is false', async () => {
    render(<Probe path={ASSET_PATH} live={false} />);
    await screen.findByTestId('keys');
    expect(subscribeMqttMessages).not.toHaveBeenCalled();
  });

  it('subscribes and applies a coalesced update when live is true', async () => {
    render(<Probe path={ASSET_PATH} live />);
    await screen.findByTestId('keys');
    expect(subscribeMqttMessages).toHaveBeenCalledWith([`${ASSET_PATH}/#`], expect.any(Function));

    await act(async () => {
      emit!({
        id: 'm1',
        topic: `${ASSET_PATH}/A/C`,
        payload: { value: 2 },
        timestamp: NOW.toISOString(),
      });
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByTestId('keys')).toHaveTextContent('A/B/value,A/C/value');
  });

  it('re-reads when the Asset changes and does not mix the two', async () => {
    const { rerender } = render(<Probe path={ASSET_PATH} live={false} />);
    await screen.findByTestId('keys');

    getUnsNodes.mockResolvedValue([
      { topic: 'CovestroAG/Dormagen/Packaging/PackLine2/X/Y', payload: { value: 9 }, lastUpdated: NOW.toISOString() },
    ]);
    rerender(<Probe path="CovestroAG/Dormagen/Packaging/PackLine2" live={false} />);

    await vi.waitFor(() => expect(screen.getByTestId('keys')).toHaveTextContent('X/Y/value'));
    expect(screen.getByTestId('keys')).not.toHaveTextContent('A/B/value');
  });

  it('reports a failed read instead of rendering an empty table', async () => {
    getUnsNodes.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<Probe path={ASSET_PATH} live={false} />);
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/useAssetMetrics.test.tsx
```

Expected: FAIL — `Failed to resolve import "./useAssetMetrics"`.

- [ ] **Step 3: Move the effect out of `LiveTab` into the hook**

Create `11_frontend/src/components/plant/useAssetMetrics.ts`. This is the code that was inside `LiveTab`'s `useEffect` and `useMemo`, verbatim except that subscribing is now conditional:

```ts
import { useEffect, useMemo, useRef, useState } from 'react'
import { unsGraphQLClient } from '../../services/graphql/client'
import type { GraphqlMetricDefinition } from '../../services/graphql/types'
import type { MqttMessage, UnsNode } from '../../types/uns'
import { subtreeTopic } from '../../lib/uns/topics'
import { MAX_LIVE_ROWS, metricRows, type MetricRowResult } from '../../lib/plant/metric-rows'

/** Current state of one topic, from the graph read or the last message on the feed. */
type NodeState = Pick<UnsNode, 'topic' | 'payload' | 'lastUpdated'>

/**
 * A busy line publishes faster than a table should re-render. Messages are collected and
 * applied on this cadence, so the feed cannot starve the main thread.
 */
const FLUSH_MS = 250

export interface AssetMetrics {
  /** null while the first read is outstanding. */
  result: MetricRowResult | null
  error: string | null
}

/**
 * Current state of every Metric under an Asset, joined to the Asset Model.
 *
 * One getUnsNodes read of the subtree and one getTopicContext read of the Enrichment.
 * With `live: true` it also subscribes to the same subtree; with `live: false` the values
 * are a snapshot, which is what a trend picker needs.
 */
export function useAssetMetrics(assetPath: string, options: { live: boolean }): AssetMetrics {
  const { live } = options
  const [nodes, setNodes] = useState<Map<string, NodeState> | null>(null)
  const [definitions, setDefinitions] = useState<GraphqlMetricDefinition[]>([])
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(new Map<string, NodeState>())

  useEffect(() => {
    let cancelled = false
    const topic = subtreeTopic(assetPath)
    setNodes(null)
    setDefinitions([])
    setError(null)
    pending.current.clear()

    Promise.all([unsGraphQLClient.getUnsNodes([topic]), unsGraphQLClient.getTopicContext(assetPath)])
      .then(([loaded, context]) => {
        if (cancelled) return
        setNodes(
          new Map(
            loaded.map((node) => [
              node.topic,
              { topic: node.topic, payload: node.payload, lastUpdated: node.lastUpdated },
            ]),
          ),
        )
        setDefinitions(context?.metricDefinitions ?? [])
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
      })

    if (!live) {
      return () => {
        cancelled = true
      }
    }

    const unsubscribe = unsGraphQLClient.subscribeMqttMessages([topic], (message: MqttMessage) => {
      pending.current.set(message.topic, {
        topic: message.topic,
        payload: message.payload,
        lastUpdated: message.timestamp,
      })
    })

    const flush = window.setInterval(() => {
      if (pending.current.size === 0) return
      const batch = pending.current
      pending.current = new Map()
      setNodes((current) => {
        const next = new Map(current ?? [])
        for (const [key, state] of batch) next.set(key, state)
        return next
      })
    }, FLUSH_MS)

    return () => {
      cancelled = true
      window.clearInterval(flush)
      unsubscribe()
    }
  }, [assetPath, live])

  const result = useMemo(
    () => (nodes === null ? null : metricRows(assetPath, [...nodes.values()], definitions, MAX_LIVE_ROWS)),
    [assetPath, nodes, definitions],
  )

  return { result, error }
}
```

- [ ] **Step 4: Reduce `LiveTab` to the hook**

Delete the `useEffect`, the `useMemo`, the `pending` ref, the `NodeState` type and the `FLUSH_MS` constant from `LiveTab.tsx` — they now live in the hook — and delete the imports that became unused (`useEffect`, `useMemo`, `useRef`, `unsGraphQLClient`, `subtreeTopic`, `MqttMessage`, `UnsNode`, `GraphqlMetricDefinition`, `metricRows`, `MAX_LIVE_ROWS`). Replace the top of the component with:

```tsx
export const LiveTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const { settings } = useUNS();
  const thresholdMinutes = settings.staleThresholdMinutes || 5;
  const { result, error } = useAssetMetrics(asset.path, { live: true });

  if (error) return <EmptyState title="Could not read current state" detail={error} />;
  if (result === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading current state…</p>;
  }
  // ...the rest of the component is unchanged: capped, empty, and the returned JSX.
```

The remaining imports are `React`, `useUNS`, `GraphqlAssetNode`, `MetricRow`, `useAssetMetrics`, `formatAge`, `isNodeStale`, `DataTable`, `Column`, `EmptyState`, `StatusPill`, `ValueWithUnit`, `NO_VALUE`.

- [ ] **Step 5: Prove the extraction changed no behaviour**

```bash
cd 11_frontend && npx vitest run src/components/plant src/lib/plant && npx tsc --noEmit
```

Expected: PASS, including every Task 10 `LiveTab` test with no assertion edited. If a `LiveTab` test needed changing, the extraction was not a refactor — revert and redo it.

- [ ] **Step 6: Commit the refactor on its own**

```bash
git add 11_frontend/src/components/plant/useAssetMetrics.ts \
  11_frontend/src/components/plant/useAssetMetrics.test.tsx \
  11_frontend/src/components/plant/tabs/LiveTab.tsx
git commit -m "refactor(frontend): extract useAssetMetrics from LiveTab

Trend needs the same Metric list Live builds, and issuing the same two reads twice
would be the wrong fix. The hook takes a live flag: Live subscribes, Trend takes a
snapshot. The LiveTab tests passed unchanged, which is what makes this a refactor."
```

- [ ] **Step 7: Write the failing Trend test**

Create `11_frontend/src/components/plant/tabs/TrendTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const useAssetMetrics = vi.fn();

vi.mock('../useAssetMetrics', () => ({
  useAssetMetrics: (...args: unknown[]) => useAssetMetrics(...args),
}));

vi.mock('../../../context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark' }),
}));

import { TrendTab } from './TrendTab';

const ASSET = {
  path: 'CovestroAG/Dormagen/Packaging/PackLine1',
  segment: 'PackLine1',
  level: 'LINE',
  name: 'Pack Line 1',
  isActive: true,
};

const NUMERIC = {
  topic: `${ASSET.path}/Cell1/MES-01/ProcessValue/GoodCount`,
  metricName: 'value',
  metricKey: 'Cell1/MES-01/ProcessValue/GoodCount/value',
  value: 1420,
  lastUpdated: '2026-09-02T10:00:00.000Z',
  definition: {
    metricKey: 'Cell1/MES-01/ProcessValue/GoodCount/value',
    displayName: 'Good count',
    unitOfMeasure: 'ea',
    decimals: 0,
    minValue: 0,
    maxValue: null,
    deadband: null,
  },
};

const TEXTUAL = {
  topic: `${ASSET.path}/Cell1/MES-01/Status/RecipeId`,
  metricName: 'value',
  metricKey: 'Cell1/MES-01/Status/RecipeId/value',
  value: 'PU-4471',
  lastUpdated: '2026-09-02T10:00:00.000Z',
  definition: undefined,
};

function metrics(rows: unknown[]) {
  return {
    result: { rows, totalRows: rows.length, hiddenComplexValues: 0, binaryTopics: [] },
    error: null,
  };
}

describe('TrendTab', () => {
  beforeEach(() => {
    useAssetMetrics.mockReset().mockReturnValue(metrics([NUMERIC, TEXTUAL]));
  });

  it('takes a snapshot rather than holding a subscription open', () => {
    render(<TrendTab asset={ASSET} />);
    expect(useAssetMetrics).toHaveBeenCalledWith(ASSET.path, { live: false });
  });

  it('charts the first numeric Metric without making the operator choose', () => {
    render(<TrendTab asset={ASSET} />);
    const frame = screen.getByTitle(/process visualization/i) as HTMLIFrameElement;
    const url = new URL(frame.src, 'http://console');
    expect(url.pathname).toBe('/grafana/d/uns-process-visualization');
    expect(url.searchParams.get('var-topic')).toBe(NUMERIC.topic);
    expect(url.searchParams.get('var-metric')).toBe('value');
    expect(url.searchParams.get('theme')).toBe('dark');
  });

  it('changes the embedded dashboard when another Metric is picked', async () => {
    const other = {
      ...NUMERIC,
      topic: `${ASSET.path}/Cell1/MES-01/ProcessValue/RejectCount`,
      metricKey: 'Cell1/MES-01/ProcessValue/RejectCount/value',
      definition: {
        ...NUMERIC.definition,
        metricKey: 'Cell1/MES-01/ProcessValue/RejectCount/value',
        displayName: 'Reject count',
      },
    };
    useAssetMetrics.mockReturnValue(metrics([NUMERIC, other, TEXTUAL]));
    render(<TrendTab asset={ASSET} />);

    await userEvent.click(screen.getByRole('button', { name: /Reject count/ }));
    const frame = screen.getByTitle(/process visualization/i) as HTMLIFrameElement;
    expect(new URL(frame.src, 'http://console').searchParams.get('var-topic')).toBe(other.topic);
  });

  it('says why a text Metric cannot be charted here instead of drawing an empty graph', async () => {
    render(<TrendTab asset={ASSET} />);
    await userEvent.click(screen.getByRole('button', { name: /RecipeId/ }));
    expect(screen.getByText(/no numeric history/i)).toBeInTheDocument();
    expect(screen.getByText(/value_text/)).toBeInTheDocument();
    expect(screen.queryByTitle(/process visualization/i)).not.toBeInTheDocument();
  });

  it('narrows the list as the operator types, and says so when nothing matches', async () => {
    render(<TrendTab asset={ASSET} />);
    await userEvent.type(screen.getByLabelText(/filter metrics/i), 'Recipe');
    expect(screen.getByRole('button', { name: /RecipeId/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Good count/ })).not.toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText(/filter metrics/i));
    await userEvent.type(screen.getByLabelText(/filter metrics/i), 'zzz');
    expect(screen.getByText(/no metric matches/i)).toBeInTheDocument();
  });

  it('offers the time ranges as a row of buttons and puts the choice in the URL', async () => {
    render(<TrendTab asset={ASSET} />);
    await userEvent.click(screen.getByRole('button', { name: '7d' }));
    const frame = screen.getByTitle(/process visualization/i) as HTMLIFrameElement;
    expect(new URL(frame.src, 'http://console').searchParams.get('from')).toBe('now-7d');
  });

  it('tells the operator to publish something when the Asset has no Metrics', () => {
    useAssetMetrics.mockReturnValue(metrics([]));
    render(<TrendTab asset={ASSET} />);
    expect(screen.getByText(/nothing has been published/i)).toBeInTheDocument();
    expect(screen.queryByTitle(/process visualization/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/TrendTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 9: Write `TrendTab`**

```tsx
import React, { useMemo, useState } from 'react';
import { useTheme } from '../../../context/ThemeContext';
import type { GraphqlAssetNode } from '../../../services/graphql/types';
import type { MetricRow } from '../../../lib/plant/metric-rows';
import { useAssetMetrics } from '../useAssetMetrics';
import { GrafanaEmbed } from '../../common/GrafanaEmbed';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill } from '../../common/StatusPill';

const RANGES: { label: string; from: string }[] = [
  { label: '1h', from: 'now-1h' },
  { label: '8h', from: 'now-8h' },
  { label: '24h', from: 'now-24h' },
  { label: '7d', from: 'now-7d' },
  { label: '30d', from: 'now-30d' },
];

/**
 * uns_metrics_1m and uns_metrics_1h are defined WHERE value_double IS NOT NULL, so a
 * Metric whose last reading was text has no row in the aggregate the dashboard reads.
 * The current value is the only evidence available in the browser, and it is enough to
 * explain the empty graph before it is drawn.
 */
function isChartable(row: MetricRow): boolean {
  return typeof row.value === 'number';
}

function label(row: MetricRow): string {
  return row.definition?.displayName ?? row.metricKey;
}

export const TrendTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const { theme } = useTheme();
  const { result, error } = useAssetMetrics(asset.path, { live: false });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [from, setFrom] = useState('now-8h');

  const rows = result?.rows ?? [];

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) => row.metricKey.toLowerCase().includes(needle) || label(row).toLowerCase().includes(needle),
    );
  }, [rows, filter]);

  // Default to the first Metric the dashboard can actually chart, so opening the tab
  // shows a trend rather than an explanation.
  const selected = useMemo(
    () => rows.find((row) => row.metricKey === selectedKey) ?? rows.find(isChartable) ?? rows[0],
    [rows, selectedKey],
  );

  if (error) return <EmptyState title="Could not read this Asset's Metrics" detail={error} />;
  if (result === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading this Asset's Metrics…</p>;
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing has been published below this Asset"
        detail="A trend needs history, and no Metric has reached the historian for this Asset. Check the Mapper for this line, or select a parent."
      />
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[300px] shrink-0 flex-col border-r border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="shrink-0 p-2">
          <label htmlFor="trend-filter" className="sr-only">
            Filter metrics
          </label>
          <input
            id="trend-filter"
            type="search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter metrics"
            className="w-full rounded border border-[#CBD5E1] bg-transparent px-2 py-1 text-[12px] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#1E293B]"
          />
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto" role="list">
          {visible.map((row) => {
            const isSelected = row.metricKey === selected?.metricKey;
            return (
              <li key={`${row.topic}#${row.metricName}`}>
                <button
                  type="button"
                  onClick={() => setSelectedKey(row.metricKey)}
                  aria-pressed={isSelected}
                  className={`flex w-full flex-col items-start gap-0.5 border-l-2 px-2 py-1 text-left focus:outline-none focus:ring-2 focus:ring-inset focus:ring-sky-500 ${
                    isSelected
                      ? 'border-sky-500 bg-sky-50 dark:bg-sky-500/10'
                      : 'border-transparent hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
                  }`}
                >
                  <span className="text-[12px] text-[#334155] dark:text-[#CBD5E1]">{label(row)}</span>
                  <span className="flex w-full items-center gap-1">
                    <span className="truncate font-mono text-[11px] text-[#64748B]">{row.metricKey}</span>
                    {!isChartable(row) && <StatusPill label="Text" tone="neutral" title="No numeric history" />}
                  </span>
                </button>
              </li>
            );
          })}
          {visible.length === 0 && (
            <li className="px-2 py-2 text-[12px] text-[#64748B]">No Metric matches “{filter}”.</li>
          )}
        </ul>
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-1 border-b border-[#E2E8F0] px-2 py-1 dark:border-[#1E293B]">
          {RANGES.map((range) => (
            <button
              key={range.label}
              type="button"
              onClick={() => setFrom(range.from)}
              aria-pressed={from === range.from}
              className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                from === range.from
                  ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
                  : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
              }`}
            >
              {range.label}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-[#64748B]">
            1-minute buckets, at least one minute behind live. Live values are on the Live tab.
          </span>
        </div>

        {selected && isChartable(selected) ? (
          <GrafanaEmbed
            title="Process Visualization"
            uid="uns-process-visualization"
            variables={{ topic: selected.topic, metric: selected.metricName }}
            from={from}
            to="now"
            theme={theme}
            className="min-h-0 flex-1"
          />
        ) : (
          <EmptyState
            title="No numeric history for this Metric"
            detail={`Its last reading was text, and the historian's 1-minute and 1-hour aggregates only cover numeric samples. The raw values are in uns_metrics.value_text, and the event log for this topic is on HISTORIAN.`}
          />
        )}
      </div>
    </div>
  );
};
```

The trailing note in the toolbar is not decoration: it is the one sentence that stops an operator reading a one-minute-old trend as a live value, and it is true because of the aggregate's `end_offset`.

- [ ] **Step 10: Run the tests**

```bash
cd 11_frontend && npx vitest run src/components/plant && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 11: Confirm the variables against the dashboard, not against memory**

```bash
cd /c/Dev/unifiednamespace && python -c "
import json
d = json.load(open('08_uns_observability/grafana/dashboards/process-visualization.json'))
print(d['uid'], [v['name'] for v in d['templating']['list']])
print([t['rawSql'][:120] for p in d['panels'] for t in p.get('targets', [])])
"
```

Expected: `uns-process-visualization ['topic', 'metric']` and a `rawSql` containing `topic LIKE '%$topic%'`. If either changed, `dashboardUrl`'s allow-list from Task 6 must change with it — that is exactly what its throw-on-unknown-variable behaviour is there to catch.

- [ ] **Step 12: Commit**

```bash
git add 11_frontend/src/components/plant/tabs/TrendTab.tsx \
  11_frontend/src/components/plant/tabs/TrendTab.test.tsx
git commit -m "feat(frontend): trend a Metric's history beside its live value

History comes from the embedded uns-process-visualization dashboard because
uns_metrics_1m is a continuous aggregate with a one-minute end_offset - correct for a
trend, wrong for a value being watched, which is why Live and Trend read different
sources. A text Metric is not charted: the aggregates are defined WHERE value_double
IS NOT NULL, so the tab says that instead of drawing an empty graph. The toolbar
states the one-minute lag so nobody reads a trend as live."
```

---

## Task 12: PLANT ▸ Shift & OEE — computed results, and the honesty ADR-0008 requires

Spec tests 1 to 5 all land in this one tab, because they are all the same requirement seen from five angles: report what `12_uns_oee` computed and nothing else.

Two repo facts decide the shape, and neither may be worked around:

1. **Nothing in the API says which Assets have an OEE unit.** `conf/oee/units.yaml` declares one, `CovestroAG/Dormagen/Production/Line1`. The OEE queries are `oeeShiftResults`, `downtimeEvents` and `downtimePareto` (`07_uns_graphql/src/uns_graphql/queries/oee.py`); none of them lists configured units, and the spec's scope adds exactly one read query, `getDowntimeReasons`. So the console reads the same authored file the engine does, as a checked-in constant with a test that fails when the two diverge. **Requires backend** to do better: a `oeeUnits` query would remove the constant, and that is the right long-term fix. It is out of this spec's scope.
2. **There is no shift-pattern API either.** `conf/oee/shifts.yaml` covers Monday to Friday only, with `exceptions` for a Christmas shutdown and an overhaul. So "the shift running now started when the last one ended" is false at every weekend and every exception. The tab therefore does not claim a shift is running. It renders the row spec section 9 asks for, worded so that it is true whether or not one is: **"After {last shift end}: not yet computed"**. Deviation from the spec's literal "In progress" wording, taken deliberately, because inventing a running shift at 03:00 on a Sunday would be exactly the kind of untruth this console exists to delete.

**Files:**
- Create: `11_frontend/src/lib/oee/units.ts`
- Test: `11_frontend/src/lib/oee/units.test.ts`
- Modify: `11_frontend/src/lib/oee/format.ts` (add `formatDurationS`)
- Modify: `11_frontend/src/lib/oee/format.test.ts` (its tests)
- Modify: `11_frontend/src/components/plant/tabs/ShiftOeeTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/ShiftOeeTab.test.tsx`

**Interfaces:**
- Consumes: `unsGraphQLClient.getOeeShiftResults(assetPath, from, to)`, `OeeShiftResult`, `OeeShiftProduct`, `formatRatio`, `statusLabel`, `isRestated`, `performanceWarning`, `NO_VALUE`, `DataTable`, `Column`, `StatusPill`, `EmptyState`.
- Produces:
  ```ts
  // src/lib/oee/units.ts
  /** Asset paths with an OEE unit in conf/oee/units.yaml. Verified against the file by test. */
  export const OEE_UNIT_PATHS: readonly string[];
  export function hasOeeUnit(assetPath: string): boolean;

  // src/lib/oee/format.ts
  /** Seconds as h:mm, or NO_VALUE. Durations on OeeShiftResult are whole seconds. */
  export function formatDurationS(seconds: number | null | undefined): string;
  ```
  Task 13 (Stops) and Task 15 (`/shift`) both call `hasOeeUnit`.

- [ ] **Step 1: Write the failing test for the unit list**

Create `11_frontend/src/lib/oee/units.test.ts`. It reads the YAML with `node:fs` rather than a parser dependency, the same way the Task 7 type-scale guard reads source files.

```ts
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { hasOeeUnit, OEE_UNIT_PATHS } from './units';

/** `  - asset: "CovestroAG/..."` — the one line per unit that names its Asset. */
function assetPathsInConf(): string[] {
  const conf = readFileSync(join(__dirname, '../../../../conf/oee/units.yaml'), 'utf8');
  const units = conf.slice(conf.indexOf('\nunits:'));
  return [...units.matchAll(/^\s*-\s*asset:\s*"([^"]+)"/gm)].map((match) => match[1]);
}

describe('OEE_UNIT_PATHS', () => {
  it('matches conf/oee/units.yaml exactly', () => {
    // The console has no API for configured units, so it reads the authored file the OEE
    // engine reads. This test is what stops the two drifting apart silently.
    expect([...OEE_UNIT_PATHS].sort()).toEqual(assetPathsInConf().sort());
  });

  it('is not empty, which would silently disable every OEE surface', () => {
    expect(OEE_UNIT_PATHS.length).toBeGreaterThan(0);
  });
});

describe('hasOeeUnit', () => {
  it('is true for a configured Asset', () => {
    expect(hasOeeUnit(OEE_UNIT_PATHS[0])).toBe(true);
  });

  it('is false for a sibling line and for an ancestor', () => {
    expect(hasOeeUnit('CovestroAG/Dormagen/Production/Line2')).toBe(false);
    expect(hasOeeUnit('CovestroAG/Dormagen/Production')).toBe(false);
  });

  it('is false for a descendant, because the unit is the Line', () => {
    // units.yaml's comment: "The subject is the Line, because that is the number a plant
    // manages." A machine below it has no OEE of its own.
    expect(hasOeeUnit(`${OEE_UNIT_PATHS[0]}/Cell1`)).toBe(false);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/oee/units.test.ts
```

Expected: FAIL — `Failed to resolve import "./units"`.

- [ ] **Step 3: Write the unit list and the duration formatter**

Create `11_frontend/src/lib/oee/units.ts`:

```ts
/**
 * Assets that OEE is reported for.
 *
 * Copied from conf/oee/units.yaml, which is where it is authored. The console has no API
 * for this: the OEE queries take an assetPath and return results, and none of them lists
 * configured units. units.test.ts fails if this list and the file disagree.
 *
 * Requires backend to remove: an `oeeUnits` query on 07_uns_graphql would make this
 * constant unnecessary, and would also let the Asset rail mark which lines have OEE.
 */
export const OEE_UNIT_PATHS: readonly string[] = ['CovestroAG/Dormagen/Production/Line1']

/**
 * Whether OEE is computed for exactly this Asset.
 *
 * Exact match, not prefix: units.yaml declares the Line as the subject, so a machine below
 * it has no OEE of its own and an Area above it has no OEE either.
 */
export function hasOeeUnit(assetPath: string): boolean {
  return OEE_UNIT_PATHS.includes(assetPath)
}
```

Append to `11_frontend/src/lib/oee/format.ts`:

```ts
/**
 * Seconds as h:mm. The durations on OeeShiftResult are whole seconds of a shift, so hours
 * and minutes is the resolution a shift lead reads; seconds would be noise.
 */
export function formatDurationS(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return NO_VALUE
  }
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  return `${hours}:${String(minutes).padStart(2, '0')}`
}
```

Append to `11_frontend/src/lib/oee/format.test.ts`:

```ts
describe('formatDurationS', () => {
  it('renders seconds as hours and minutes', () => {
    expect(formatDurationS(28_800)).toBe('8:00')
    expect(formatDurationS(3_900)).toBe('1:05')
  })

  it('renders a real zero duration as zero, not as absent', () => {
    expect(formatDurationS(0)).toBe('0:00')
  })

  it('renders an absent duration as an em dash', () => {
    expect(formatDurationS(null)).toBe('—')
  })
})
```

Add `formatDurationS` to the existing import at the top of `format.test.ts`.

- [ ] **Step 4: Run both library test files**

```bash
cd 11_frontend && npx vitest run src/lib/oee && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 5: Write the failing tab test**

Create `11_frontend/src/components/plant/tabs/ShiftOeeTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OeeShiftResult } from '../../../types/oee';

const getOeeShiftResults = vi.fn();

vi.mock('../../../services/graphql/client', () => ({
  unsGraphQLClient: { getOeeShiftResults: (...args: unknown[]) => getOeeShiftResults(...args) },
}));

vi.mock('../../../lib/oee/units', () => ({
  OEE_UNIT_PATHS: ['CovestroAG/Dormagen/Production/Line1'],
  hasOeeUnit: (path: string) => path === 'CovestroAG/Dormagen/Production/Line1',
}));

import { ShiftOeeTab } from './ShiftOeeTab';

const LINE1 = {
  path: 'CovestroAG/Dormagen/Production/Line1',
  segment: 'Line1',
  level: 'LINE',
  name: 'Line 1',
  isActive: true,
};

const LINE2 = { ...LINE1, path: 'CovestroAG/Dormagen/Production/Line2', segment: 'Line2', name: 'Line 2' };

const NOW = new Date('2026-09-02T12:00:00.000Z');

function shift(overrides: Partial<OeeShiftResult> = {}): OeeShiftResult {
  return {
    assetPath: LINE1.path,
    shiftStart: '2026-09-01T04:00:00.000Z',
    shiftEnd: '2026-09-01T12:00:00.000Z',
    shiftLabel: 'A',
    loadingTimeS: 28_800,
    runTimeS: 25_200,
    plannedDownS: 1_800,
    unplannedDownS: 1_800,
    goodCount: 8_100,
    rejectCount: 100,
    totalCount: 8_200,
    availability: 0.875,
    performance: 0.964,
    performanceRaw: 0.964,
    quality: 0.9878,
    oee: 0.8332,
    status: 'OK',
    revision: 1,
    computedAt: '2026-09-01T12:20:00.000Z',
    publishedAt: '2026-09-01T12:20:05.000Z',
    products: [
      { productCode: 'R-100-STD', goodCount: 8_100, rejectCount: 100, totalCount: 8_200, idealCycleTimeS: 3 },
    ],
    ...overrides,
  };
}

describe('ShiftOeeTab', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    getOeeShiftResults.mockReset().mockResolvedValue([shift()]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Spec test 5.
  it('says no OEE unit is configured, and does not ask for results', async () => {
    render(<ShiftOeeTab asset={LINE2} />);
    expect(await screen.findByText(/no oee unit is configured/i)).toBeInTheDocument();
    expect(screen.getByText(/conf\/oee\/units\.yaml/)).toBeInTheDocument();
    expect(getOeeShiftResults).not.toHaveBeenCalled();
  });

  it('reads results for the configured Asset over the selected range', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    await screen.findByText('83.3%');
    expect(getOeeShiftResults).toHaveBeenCalledWith(LINE1.path, expect.any(String), expect.any(String));
    const [, from, to] = getOeeShiftResults.mock.calls[0];
    expect(new Date(from).getTime()).toBeLessThan(new Date(to).getTime());
    expect(new Date(to).toISOString()).toBe(NOW.toISOString());
  });

  it('shows the four ratios of a computed shift', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    const row = (await screen.findByText('83.3%')).closest('tr')!;
    expect(row.textContent).toContain('87.5%');
    expect(row.textContent).toContain('96.4%');
    expect(row.textContent).toContain('98.8%');
    expect(row.textContent).toContain('8:00');
  });

  // Spec test 1.
  it('renders a null ratio as an em dash, never as zero', async () => {
    getOeeShiftResults.mockResolvedValue([
      shift({
        loadingTimeS: 0,
        runTimeS: 0,
        goodCount: 0,
        rejectCount: 0,
        totalCount: 0,
        availability: null,
        performance: null,
        performanceRaw: null,
        quality: null,
        oee: null,
        status: 'NO_LOADING_TIME',
      }),
    ]);
    render(<ShiftOeeTab asset={LINE1} />);
    const row = (await screen.findByText(/no scheduled time/i)).closest('tr')!;
    expect(row.textContent).not.toContain('0.0%');
    expect(row.textContent).toContain('—');
    // A zero count is a fact and still reads as zero.
    expect(row.textContent).toContain('0:00');
  });

  // Spec test 2.
  it('offers no percentage for the time after the last closed shift', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    const row = (await screen.findByTestId('shift-not-yet-computed'));
    expect(row.textContent).toMatch(/not yet computed/i);
    expect(row.textContent).not.toMatch(/%/);
  });

  // Spec test 3.
  it('marks a restated shift and says when it was recomputed', async () => {
    getOeeShiftResults.mockResolvedValue([
      shift({ revision: 3, computedAt: '2026-09-02T09:15:00.000Z' }),
    ]);
    render(<ShiftOeeTab asset={LINE1} />);
    const badge = await screen.findByText(/restated/i);
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute('title')).toMatch(/revision 3/i);
    expect(badge.getAttribute('title')).toContain('2026-09-02');
  });

  it('does not mark a first computation as restated', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    await screen.findByText('83.3%');
    expect(screen.queryByText(/restated/i)).not.toBeInTheDocument();
  });

  it('marks a computed shift that is not on the broker yet', async () => {
    getOeeShiftResults.mockResolvedValue([shift({ publishedAt: null })]);
    render(<ShiftOeeTab asset={LINE1} />);
    const badge = await screen.findByText(/not published/i);
    expect(badge.getAttribute('title')).toMatch(/KPI\/ShiftOee/);
  });

  it('does not mark a published shift', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    await screen.findByText('83.3%');
    expect(screen.queryByText(/not published/i)).not.toBeInTheDocument();
  });

  // Spec test 4.
  it('cautions when performance exceeded 100% before clamping', async () => {
    getOeeShiftResults.mockResolvedValue([shift({ performance: 1, performanceRaw: 1.18 })]);
    render(<ShiftOeeTab asset={LINE1} />);
    const badge = await screen.findByText(/check cycle time/i);
    expect(badge.getAttribute('title')).toMatch(/rated cycle time is too slow/i);
  });

  it('breaks a selected shift down by product', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    await userEvent.click(await screen.findByText('83.3%'));
    expect(screen.getByText('R-100-STD')).toBeInTheDocument();
    expect(screen.getByText('3 s/unit')).toBeInTheDocument();
  });

  it('explains an empty range instead of showing a blank table', async () => {
    getOeeShiftResults.mockResolvedValue([]);
    render(<ShiftOeeTab asset={LINE1} />);
    expect(await screen.findByText(/no shift has closed/i)).toBeInTheDocument();
    expect(screen.queryByTestId('shift-not-yet-computed')).not.toBeInTheDocument();
  });

  it('re-reads when the range changes', async () => {
    render(<ShiftOeeTab asset={LINE1} />);
    await screen.findByText('83.3%');
    await userEvent.click(screen.getByRole('button', { name: '30d' }));
    await vi.waitFor(() => expect(getOeeShiftResults).toHaveBeenCalledTimes(2));
    const firstSpan = Date.parse(getOeeShiftResults.mock.calls[0][2]) - Date.parse(getOeeShiftResults.mock.calls[0][1]);
    const secondSpan = Date.parse(getOeeShiftResults.mock.calls[1][2]) - Date.parse(getOeeShiftResults.mock.calls[1][1]);
    expect(secondSpan).toBeGreaterThan(firstSpan);
  });

  it('surfaces a failed read rather than an empty range message', async () => {
    getOeeShiftResults.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<ShiftOeeTab asset={LINE1} />);
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/ShiftOeeTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 7: Write `ShiftOeeTab`**

```tsx
import React, { useEffect, useMemo, useState } from 'react';
import { unsGraphQLClient } from '../../../services/graphql/client';
import type { GraphqlAssetNode } from '../../../services/graphql/types';
import type { OeeShiftResult } from '../../../types/oee';
import { hasOeeUnit } from '../../../lib/oee/units';
import {
  formatDurationS,
  formatRatio,
  isRestated,
  performanceWarning,
  statusLabel,
} from '../../../lib/oee/format';
import { DataTable, type Column } from '../../common/DataTable';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill } from '../../common/StatusPill';

const RANGES: { label: string; days: number }[] = [
  { label: '24h', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
];

function rowKey(result: OeeShiftResult): string {
  return `${result.shiftStart}#${result.shiftLabel}`;
}

/** A shift's day and label, which is how a shift lead names one. */
function shiftName(result: OeeShiftResult): string {
  return `${result.shiftStart.slice(0, 10)} · ${result.shiftLabel}`;
}

const COLUMNS: Column<OeeShiftResult>[] = [
  { key: 'shift', header: 'Shift', render: shiftName },
  { key: 'loading', header: 'Scheduled', align: 'right', render: (r) => formatDurationS(r.loadingTimeS) },
  { key: 'run', header: 'Running', align: 'right', render: (r) => formatDurationS(r.runTimeS) },
  {
    key: 'stops',
    header: 'Stops P/U',
    align: 'right',
    render: (r) => `${formatDurationS(r.plannedDownS)} / ${formatDurationS(r.unplannedDownS)}`,
  },
  { key: 'good', header: 'Good', align: 'right', render: (r) => r.goodCount.toLocaleString() },
  { key: 'reject', header: 'Reject', align: 'right', render: (r) => r.rejectCount.toLocaleString() },
  { key: 'availability', header: 'A', align: 'right', render: (r) => formatRatio(r.availability) },
  { key: 'performance', header: 'P', align: 'right', render: (r) => formatRatio(r.performance) },
  { key: 'quality', header: 'Q', align: 'right', render: (r) => formatRatio(r.quality) },
  { key: 'oee', header: 'OEE', align: 'right', render: (r) => formatRatio(r.oee) },
  { key: 'status', header: 'Status', render: (r) => statusLabel(r.status) },
  {
    key: 'flags',
    header: '',
    render: (r) => {
      const caution = performanceWarning(r);
      return (
        <span className="flex gap-1">
          {isRestated(r) && (
            <StatusPill
              label="Restated"
              tone="info"
              title={`Revision ${r.revision}, recomputed ${r.computedAt ?? 'at an unrecorded time'} after late data arrived`}
            />
          )}
          {caution && <StatusPill label="Check cycle time" tone="warn" title={caution} />}
          {r.publishedAt === null && (
            <StatusPill
              label="Not published"
              tone="warn"
              title="Computed but not yet published to the broker, so a consumer reading this Asset's KPI/ShiftOee topic does not have it"
            />
          )}
        </span>
      );
    },
  },
];

const PRODUCT_COLUMNS: Column<OeeShiftResult['products'][number]>[] = [
  { key: 'product', header: 'Product', mono: true, render: (p) => p.productCode },
  { key: 'good', header: 'Good', align: 'right', render: (p) => p.goodCount.toLocaleString() },
  { key: 'reject', header: 'Reject', align: 'right', render: (p) => p.rejectCount.toLocaleString() },
  { key: 'total', header: 'Total', align: 'right', render: (p) => p.totalCount.toLocaleString() },
  {
    key: 'ideal',
    header: 'Rated cycle',
    align: 'right',
    // The rated cycle time is per product, and a missing one is why performance is null.
    render: (p) => (p.idealCycleTimeS === null ? 'not authored' : `${p.idealCycleTimeS} s/unit`),
  },
];

export const ShiftOeeTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const configured = hasOeeUnit(asset.path);
  const [days, setDays] = useState(7);
  const [results, setResults] = useState<OeeShiftResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!configured) return;
    let cancelled = false;
    setResults(null);
    setError(null);
    setSelected(undefined);
    const to = new Date();
    const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
    unsGraphQLClient
      .getOeeShiftResults(asset.path, from.toISOString(), to.toISOString())
      .then((loaded) => {
        if (!cancelled) setResults(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [asset.path, configured, days]);

  const selectedResult = useMemo(
    () => results?.find((result) => rowKey(result) === selected),
    [results, selected],
  );

  if (!configured) {
    return (
      <EmptyState
        title="No OEE unit is configured for this Asset"
        detail="OEE is only computed for Assets declared in conf/oee/units.yaml, each with a shift pattern and rated cycle times. Adding this Asset there, and restarting the OEE service, is what makes this tab show numbers."
      />
    );
  }
  if (error) return <EmptyState title="Could not read shift results" detail={error} />;
  if (results === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading shift results…</p>;
  }

  // oeeShiftResults returns oldest first (queries/oee.py). Newest first is what a shift
  // lead wants, so the last closed shift is the first row.
  const newestFirst = [...results].reverse();
  const lastClosed = newestFirst[0];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-[#E2E8F0] px-2 py-1 dark:border-[#1E293B]">
        {RANGES.map((range) => (
          <button
            key={range.label}
            type="button"
            onClick={() => setDays(range.days)}
            aria-pressed={days === range.days}
            className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
              days === range.days
                ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
                : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
            }`}
          >
            {range.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-[#64748B]">
          A shift is computed after it closes, roughly twenty minutes later. Late data restates
          a shift and raises its revision.
        </span>
      </div>

      {lastClosed && (
        <p
          data-testid="shift-not-yet-computed"
          className="shrink-0 border-b border-[#E2E8F0] px-3 py-1.5 text-[12px] text-[#64748B] dark:border-[#1E293B]"
        >
          After {lastClosed.shiftEnd}: not yet computed. A shift appears here once it has closed
          and been computed; if none is running, nothing will.
        </p>
      )}

      <div className="min-h-0 flex-1">
        <DataTable
          columns={COLUMNS}
          rows={newestFirst}
          rowKey={rowKey}
          onRowClick={(result) => setSelected(rowKey(result))}
          selectedKey={selected}
          empty={
            <EmptyState
              title="No shift has closed in this range"
              detail="Widen the range, or check that the OEE service is running and that this Asset's shift pattern in conf/oee/shifts.yaml covers these days."
            />
          }
        />
      </div>

      {selectedResult && (
        <div className="max-h-[40%] shrink-0 overflow-y-auto border-t border-[#E2E8F0] dark:border-[#1E293B]">
          <h3 className="px-3 pt-2 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
            {shiftName(selectedResult)} by product
          </h3>
          <DataTable
            columns={PRODUCT_COLUMNS}
            rows={selectedResult.products}
            rowKey={(product) => product.productCode}
            empty={
              <EmptyState
                title="No product breakdown for this shift"
                detail="Counts were not split by product, which happens when the recipe Metric published nothing during the shift."
              />
            }
          />
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 8: Run the tests**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/ShiftOeeTab.test.tsx src/lib/oee && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 9: Prove no component turns a null ratio into a number**

```bash
cd 11_frontend && grep -rn "availability\|performance\|quality\|\.oee\b" src/components | grep -n "?? 0\|(|| 0)\|toFixed" || echo "clean"
```

Expected: `clean`. Every ratio goes through `formatRatio`. A hit here is ADR-0008 being undone.

- [ ] **Step 10: Commit**

```bash
git add 11_frontend/src/lib/oee/ 11_frontend/src/components/plant/tabs/ShiftOeeTab.tsx \
  11_frontend/src/components/plant/tabs/ShiftOeeTab.test.tsx
git commit -m "feat(frontend): report computed shift OEE without inventing any of it

Null ratios render as a dash, a restated shift says which revision and when, and
performance above 100% before clamping is flagged rather than hidden - ADR-0008 asks
for all three. An Asset with no unit in conf/oee/units.yaml says so and issues no
query, so no screen implies OEE exists where it does not.

Two honest limits are recorded in code: the configured-unit list is a constant
checked against conf/oee/units.yaml by test because no query lists units, and the
current shift is described as 'not yet computed' rather than 'in progress' because
conf/oee/shifts.yaml has weekend and exception gaps and the browser cannot know
whether one is running."
```

---

## Task 13: PLANT ▸ Stops — the one write this console makes

Spec test 6 lives here, and so does the second half of spec test 5.

Read `07_uns_graphql/src/uns_graphql/mutations/oee.py` before writing this task. Three sentences in it decide the design:

1. `assign_downtime_reason` is the **only** write in the OEE surface, and its module docstring says why: "An OEE number is computed, never edited. What a human legitimately knows better than the engine is *why* a machine stopped."
2. It "queues that shift for recomputation", and "Reassignment can change the OEE, because a reason's `is_planned` flag moves the interval between Unplanned Down and excluded time." So the dialog must not present itself as relabelling a row. The operator is triggering a recomputation, and the tab says so.
3. `assigned_by` carries the description "Attested by the caller, not authenticated: this platform has no authentication anywhere." The dialog therefore asks the operator to type a name and states plainly that nothing verifies it. It does **not** send `AuthContext`'s fabricated user, which would dress a made-up identity as a real one. **This field is deliberately temporary**: `docs/superpowers/plans/2026-09-02-console-authentication.md` Task 6 deletes the `assignedBy` argument from the schema and takes the name from the validated token, and its Step 7 enumerates every edit that lands here — the field, the fourth argument, the "nothing verifies it" sentence, the `useAuth`-is-absent test, and the stops-table tooltip. Write this task as specified anyway; a typed name the UI calls unverified is honest for a console with no identity, and the alternative of recording nothing loses information for no gain.

`share` is documented on `DowntimeParetoBucket` as "Fraction of the window's total downtime, 0..1", and the type description says "largest first" — so `formatRatio` renders it and the server's order is kept, with a defensive sort because a bar list that is not descending is unreadable.

**Files:**
- Create: `11_frontend/src/components/plant/ParetoBars.tsx`
- Test: `11_frontend/src/components/plant/ParetoBars.test.tsx`
- Create: `11_frontend/src/components/plant/ReassignReasonDialog.tsx`
- Test: `11_frontend/src/components/plant/ReassignReasonDialog.test.tsx`
- Modify: `11_frontend/src/components/plant/tabs/StopsTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/StopsTab.test.tsx`

**Interfaces:**
- Consumes: `getDowntimeEvents`, `getDowntimePareto`, `getDowntimeReasons`, `assignDowntimeReason` (foundation Task 8), `DowntimeEvent`, `DowntimeParetoBucket`, `DowntimeReason` (foundation Task 7), `formatRatio`, `formatDurationS` (Task 12), `hasOeeUnit` (Task 12), `DataTable`, `Column`, `StatusPill`, `EmptyState`.
- Produces:
  ```tsx
  export const ParetoBars: React.FC<{ buckets: DowntimeParetoBucket[] }>;

  export const ReassignReasonDialog: React.FC<{
    event: DowntimeEvent;
    onCancel: () => void;
    onAssigned: (updated: DowntimeEvent) => void;
  }>;
  ```
  Task 15 (`/shift`) renders `StopsTab` and `ParetoBars`.

- [ ] **Step 1: Write the failing Pareto test**

Create `11_frontend/src/components/plant/ParetoBars.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DowntimeParetoBucket } from '../../types/oee';
import { ParetoBars } from './ParetoBars';

function bucket(overrides: Partial<DowntimeParetoBucket> = {}): DowntimeParetoBucket {
  return {
    reasonCode: 'BREAKDOWN',
    displayName: 'Breakdown',
    category: 'FAILURE',
    isPlanned: false,
    eventCount: 4,
    totalSeconds: 5_400,
    share: 0.62,
    ...overrides,
  };
}

describe('ParetoBars', () => {
  it('renders one bar per reason with its share, duration and count', () => {
    render(<ParetoBars buckets={[bucket()]} />);
    const row = screen.getByTestId('pareto-BREAKDOWN');
    expect(row.textContent).toContain('Breakdown');
    expect(row.textContent).toContain('62.0%');
    expect(row.textContent).toContain('1:30');
    expect(row.textContent).toContain('4');
  });

  it('sizes the bar by share', () => {
    render(<ParetoBars buckets={[bucket({ share: 0.25 })]} />);
    expect(screen.getByTestId('pareto-bar-BREAKDOWN').style.width).toBe('25%');
  });

  it('distinguishes planned from unplanned in words, not colour alone', () => {
    render(
      <ParetoBars
        buckets={[
          bucket({ share: 0.6 }),
          bucket({ reasonCode: 'CHANGEOVER', displayName: 'Changeover', category: 'PLANNED', isPlanned: true, share: 0.4 }),
        ]}
      />,
    );
    expect(screen.getByTestId('pareto-BREAKDOWN').textContent).toContain('Unplanned');
    expect(screen.getByTestId('pareto-CHANGEOVER').textContent).toContain('Planned');
  });

  it('orders largest first even if the server did not', () => {
    render(
      <ParetoBars
        buckets={[
          bucket({ reasonCode: 'SMALL', share: 0.1 }),
          bucket({ reasonCode: 'BIG', share: 0.9 }),
        ]}
      />,
    );
    const codes = screen.getAllByTestId(/^pareto-[A-Z]+$/).map((row) => row.dataset.testid);
    expect(codes).toEqual(['pareto-BIG', 'pareto-SMALL']);
  });

  it('says there was no downtime rather than drawing nothing', () => {
    render(<ParetoBars buckets={[]} />);
    expect(screen.getByText(/no downtime in this range/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/ParetoBars.test.tsx
```

Expected: FAIL — `Failed to resolve import "./ParetoBars"`.

- [ ] **Step 3: Write `ParetoBars`**

```tsx
import React from 'react';
import type { DowntimeParetoBucket } from '../../types/oee';
import { formatDurationS, formatRatio } from '../../lib/oee/format';

/**
 * The downtime Pareto as a horizontal bar list.
 *
 * `share` is documented as a fraction 0..1 of the window's total downtime, and the buckets
 * arrive largest first. Planned and unplanned are labelled in words as well as coloured,
 * because whether a stop counted against Availability is the whole point of the chart and
 * an operator should not have to distinguish two hues to learn it.
 */
export const ParetoBars: React.FC<{ buckets: DowntimeParetoBucket[] }> = ({ buckets }) => {
  if (buckets.length === 0) {
    return (
      <p className="px-3 py-2 text-[11px] text-[#64748B]">
        No downtime in this range. Either the line did not stop, or no shift covering it has
        been computed yet.
      </p>
    );
  }

  const ordered = [...buckets].sort((a, b) => b.share - a.share);

  return (
    <ul className="flex flex-col gap-1.5 px-3 py-2">
      {ordered.map((bucket) => (
        <li key={bucket.reasonCode} data-testid={`pareto-${bucket.reasonCode}`}>
          <div className="flex items-baseline justify-between gap-2 text-[11px]">
            <span className="truncate text-[#0F172A] dark:text-[#E2E8F0]" title={bucket.reasonCode}>
              {bucket.displayName}
            </span>
            <span className="shrink-0 tabular-nums text-[#64748B]">
              {formatRatio(bucket.share)} · {formatDurationS(bucket.totalSeconds)} · {bucket.eventCount}
            </span>
          </div>
          <div className="mt-0.5 h-2 w-full rounded-sm bg-[#E2E8F0] dark:bg-[#1E293B]">
            <div
              data-testid={`pareto-bar-${bucket.reasonCode}`}
              className={`h-2 rounded-sm ${bucket.isPlanned ? 'bg-sky-500' : 'bg-amber-500'}`}
              style={{ width: `${bucket.share * 100}%` }}
            />
          </div>
          <span className="text-[11px] text-[#64748B]">
            {bucket.isPlanned ? 'Planned' : 'Unplanned'} · {bucket.category}
          </span>
        </li>
      ))}
    </ul>
  );
};
```

- [ ] **Step 4: Run it**

```bash
cd 11_frontend && npx vitest run src/components/plant/ParetoBars.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Write the failing dialog test**

This is spec test 6. Create `11_frontend/src/components/plant/ReassignReasonDialog.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DowntimeEvent } from '../../types/oee';

const getDowntimeReasons = vi.fn();
const assignDowntimeReason = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getDowntimeReasons: () => getDowntimeReasons(),
    assignDowntimeReason: (...args: unknown[]) => assignDowntimeReason(...args),
  },
}));

import { ReassignReasonDialog } from './ReassignReasonDialog';

const EVENT: DowntimeEvent = {
  id: '11',
  assetPath: 'CovestroAG/Dormagen/Production/Line1',
  shiftStart: '2026-09-01T04:00:00.000Z',
  startedAt: '2026-09-01T07:12:00.000Z',
  endedAt: '2026-09-01T07:31:00.000Z',
  durationS: 1_140,
  stateValue: 'STOPPED',
  reasonCode: 'UNASSIGNED',
  reasonDisplayName: 'Unassigned',
  reasonCategory: 'UNKNOWN',
  isPlanned: false,
  reasonSource: 'AUTO',
  assignedBy: null,
  assignedAt: null,
  note: '',
};

// CHANGEOVER is deliberately a code no event in the window carries, which is the whole
// reason getDowntimeReasons exists: downtimePareto only returns codes already in use.
const REASONS = [
  { code: 'CHANGEOVER', displayName: 'Changeover', category: 'PLANNED', isPlanned: true },
  { code: 'BREAKDOWN', displayName: 'Breakdown', category: 'FAILURE', isPlanned: false },
];

describe('ReassignReasonDialog', () => {
  beforeEach(() => {
    getDowntimeReasons.mockReset().mockResolvedValue(REASONS);
    assignDowntimeReason.mockReset().mockResolvedValue({
      ...EVENT,
      reasonCode: 'BREAKDOWN',
      reasonDisplayName: 'Breakdown',
      reasonCategory: 'FAILURE',
      reasonSource: 'MANUAL',
      assignedBy: 'shift.lead',
      assignedAt: '2026-09-02T12:00:00.000Z',
      note: 'seal failed',
    });
  });

  // Spec test 6.
  it('offers every authored code, including one no event carries', async () => {
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    expect(await screen.findByRole('option', { name: /BREAKDOWN/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /CHANGEOVER/ })).toBeInTheDocument();
  });

  // Spec test 6.
  it('sends the chosen code and the note', async () => {
    const onAssigned = vi.fn();
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={onAssigned} />);
    await screen.findByRole('option', { name: /BREAKDOWN/ });
    await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'BREAKDOWN');
    await userEvent.type(screen.getByLabelText(/note/i), 'seal failed');
    await userEvent.type(screen.getByLabelText(/your name/i), 'shift.lead');
    await userEvent.click(screen.getByRole('button', { name: /reassign and recompute/i }));
    await waitFor(() =>
      expect(assignDowntimeReason).toHaveBeenCalledWith('11', 'BREAKDOWN', 'seal failed', 'shift.lead'),
    );
    expect(onAssigned).toHaveBeenCalledWith(expect.objectContaining({ reasonSource: 'MANUAL' }));
  });

  it('sends no name rather than an empty one when the field is left blank', async () => {
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    await screen.findByRole('option', { name: /BREAKDOWN/ });
    await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'BREAKDOWN');
    await userEvent.click(screen.getByRole('button', { name: /reassign and recompute/i }));
    await waitFor(() => expect(assignDowntimeReason).toHaveBeenCalledWith('11', 'BREAKDOWN', undefined, undefined));
  });

  it('says the name is unverified and that the shift will be recomputed', async () => {
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    expect(await screen.findByText(/nothing verifies it/i)).toBeInTheDocument();
    expect(screen.getByText(/recomputed/i)).toBeInTheDocument();
  });

  it('never sends a signed-in user the operator did not type', async () => {
    // AuthContext's user is fabricated in the browser. Sending it as assignedBy would put a
    // name into plant data that no one attested to.
    const source = await import('./ReassignReasonDialog?raw').then((m) => m.default as string);
    expect(source).not.toMatch(/useAuth|AuthContext/);
  });

  it('cannot be submitted until a reason is chosen', async () => {
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    await screen.findByRole('option', { name: /BREAKDOWN/ });
    expect(screen.getByRole('button', { name: /reassign and recompute/i })).toBeDisabled();
  });

  it('shows the server’s refusal and stays open', async () => {
    assignDowntimeReason.mockRejectedValue(new Error("'NOPE' is not an authored reason code"));
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    await screen.findByRole('option', { name: /BREAKDOWN/ });
    await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'BREAKDOWN');
    await userEvent.click(screen.getByRole('button', { name: /reassign and recompute/i }));
    expect(await screen.findByText(/not an authored reason code/)).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('explains a failure to load the codes instead of offering an empty picker', async () => {
    getDowntimeReasons.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });

  it('closes on Escape and on Cancel', async () => {
    const onCancel = vi.fn();
    render(<ReassignReasonDialog event={EVENT} onCancel={onCancel} onAssigned={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    await userEvent.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 6: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/ReassignReasonDialog.test.tsx
```

Expected: FAIL — `Failed to resolve import "./ReassignReasonDialog"`.

- [ ] **Step 7: Write `ReassignReasonDialog`**

```tsx
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { DowntimeEvent, DowntimeReason } from '../../types/oee';
import { formatDurationS } from '../../lib/oee/format';

interface Props {
  event: DowntimeEvent;
  onCancel: () => void;
  onAssigned: (updated: DowntimeEvent) => void;
}

/**
 * Attribute a stop to a reason code by hand.
 *
 * The picker is fed by getDowntimeReasons, not by the Pareto: the Pareto only contains codes
 * already in use, so a freshly authored code would be unreachable.
 *
 * The name is a free-text field with a disclosure, because the mutation's own argument
 * description says it is "Attested by the caller, not authenticated". The console has a
 * browser-local AuthContext user, and sending it here would turn a made-up name into a
 * plant-data attribution. The authentication cycle replaces this field with the token subject.
 */
export const ReassignReasonDialog: React.FC<Props> = ({ event, onCancel, onAssigned }) => {
  const [reasons, setReasons] = useState<DowntimeReason[] | null>(null);
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const [attestedBy, setAttestedBy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient
      .getDowntimeReasons()
      .then((loaded) => {
        if (cancelled) return;
        setReasons(loaded);
        selectRef.current?.focus();
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKey = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  /** Grouped by category, which is how reasons.yaml authors them. */
  const groups = useMemo(() => {
    const byCategory = new Map<string, DowntimeReason[]>();
    for (const reason of reasons ?? []) {
      const list = byCategory.get(reason.category) ?? [];
      list.push(reason);
      byCategory.set(reason.category, list);
    }
    return [...byCategory.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [reasons]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await unsGraphQLClient.assignDowntimeReason(
        event.id,
        code,
        // Empty strings would record an empty note and an empty attribution as though they
        // were values. Absent is the truth, and the arguments are nullable.
        note.trim() === '' ? undefined : note.trim(),
        attestedBy.trim() === '' ? undefined : attestedBy.trim(),
      );
      onAssigned(updated);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reassign-title"
        className="w-[520px] max-w-full rounded border border-[#CBD5E1] bg-white p-4 text-[12px] shadow-xl dark:border-[#334155] dark:bg-[#0F172A]"
      >
        <h2 id="reassign-title" className="text-[13px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">
          Reassign this stop
        </h2>
        <p className="mt-1 font-mono text-[11px] text-[#64748B]">
          {event.startedAt} → {event.endedAt} · {formatDurationS(event.durationS)} · state{' '}
          {event.stateValue} · now {event.reasonDisplayName}
        </p>

        <label className="mt-3 block" htmlFor="reassign-reason">
          Reason
        </label>
        <select
          id="reassign-reason"
          ref={selectRef}
          value={code}
          onChange={(changeEvent) => setCode(changeEvent.target.value)}
          className="mt-1 w-full rounded border border-[#CBD5E1] bg-transparent px-2 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
        >
          <option value="">Choose a reason…</option>
          {groups.map(([category, list]) => (
            <optgroup key={category} label={category}>
              {list.map((reason) => (
                <option key={reason.code} value={reason.code}>
                  {reason.code} — {reason.displayName} ({reason.isPlanned ? 'planned' : 'unplanned'})
                </option>
              ))}
            </optgroup>
          ))}
        </select>

        <label className="mt-3 block" htmlFor="reassign-note">
          Note
        </label>
        <textarea
          id="reassign-note"
          rows={2}
          value={note}
          onChange={(changeEvent) => setNote(changeEvent.target.value)}
          className="mt-1 w-full rounded border border-[#CBD5E1] bg-transparent px-2 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
        />

        <label className="mt-3 block" htmlFor="reassign-by">
          Your name
        </label>
        <input
          id="reassign-by"
          value={attestedBy}
          onChange={(changeEvent) => setAttestedBy(changeEvent.target.value)}
          className="mt-1 w-full rounded border border-[#CBD5E1] bg-transparent px-2 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
        />
        <p className="mt-1 text-[11px] text-[#64748B]">
          Stored exactly as typed. Nothing verifies it — this platform has no authentication
          yet, so the name is a claim, not an identity.
        </p>

        <p className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-[#0F172A] dark:text-[#E2E8F0]">
          The shift will be recomputed. A planned reason excludes the stop from Unplanned Down,
          so this Asset’s OEE for {event.shiftStart.slice(0, 10)} can change and will appear as
          a restated revision.
        </p>

        {error && (
          <p role="alert" className="mt-2 text-[11px] text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-2 py-1 text-[#64748B] hover:bg-[#F1F5F9] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:hover:bg-[#1E293B]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={code === '' || saving}
            className="rounded bg-sky-600 px-2 py-1 text-white disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            {saving ? 'Reassigning…' : 'Reassign and recompute'}
          </button>
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 8: Run the dialog tests**

```bash
cd 11_frontend && npx vitest run src/components/plant/ReassignReasonDialog.test.tsx
```

Expected: PASS. The `?raw` import in the "never sends a signed-in user" test relies on Vite's raw loader, which `vitest.config.ts` inherits from the Vite config; if it fails to resolve, replace that test's body with a `readFileSync` of the component the way `src/lib/oee/units.test.ts` reads the YAML. Do not delete the test — it is the guard on the one claim this dialog makes about itself.

- [ ] **Step 9: Write the failing Stops tab test**

Create `11_frontend/src/components/plant/tabs/StopsTab.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DowntimeEvent, DowntimeParetoBucket } from '../../../types/oee';

const getDowntimeEvents = vi.fn();
const getDowntimePareto = vi.fn();

vi.mock('../../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getDowntimeEvents: (...args: unknown[]) => getDowntimeEvents(...args),
    getDowntimePareto: (...args: unknown[]) => getDowntimePareto(...args),
  },
}));

vi.mock('../../../lib/oee/units', () => ({
  OEE_UNIT_PATHS: ['CovestroAG/Dormagen/Production/Line1'],
  hasOeeUnit: (path: string) => path === 'CovestroAG/Dormagen/Production/Line1',
}));

vi.mock('../ReassignReasonDialog', () => ({
  ReassignReasonDialog: ({ event, onAssigned }: { event: DowntimeEvent; onAssigned: (e: DowntimeEvent) => void }) => (
    <div role="dialog">
      <span>reassigning {event.id}</span>
      <button type="button" onClick={() => onAssigned({ ...event, reasonCode: 'BREAKDOWN', reasonDisplayName: 'Breakdown', reasonSource: 'MANUAL' })}>
        confirm
      </button>
    </div>
  ),
}));

import { StopsTab } from './StopsTab';

const LINE1 = {
  path: 'CovestroAG/Dormagen/Production/Line1',
  segment: 'Line1',
  level: 'LINE',
  name: 'Line 1',
  isActive: true,
};
const LINE2 = { ...LINE1, path: 'CovestroAG/Dormagen/Production/Line2', segment: 'Line2', name: 'Line 2' };

const EVENT: DowntimeEvent = {
  id: '11',
  assetPath: LINE1.path,
  shiftStart: '2026-09-01T04:00:00.000Z',
  startedAt: '2026-09-01T07:12:00.000Z',
  endedAt: '2026-09-01T07:31:00.000Z',
  durationS: 1_140,
  stateValue: 'STOPPED',
  reasonCode: 'UNASSIGNED',
  reasonDisplayName: 'Unassigned',
  reasonCategory: 'UNKNOWN',
  isPlanned: false,
  reasonSource: 'AUTO',
  assignedBy: null,
  assignedAt: null,
  note: '',
};

const BUCKET: DowntimeParetoBucket = {
  reasonCode: 'UNASSIGNED',
  displayName: 'Unassigned',
  category: 'UNKNOWN',
  isPlanned: false,
  eventCount: 1,
  totalSeconds: 1_140,
  share: 1,
};

describe('StopsTab', () => {
  beforeEach(() => {
    getDowntimeEvents.mockReset().mockResolvedValue([EVENT]);
    getDowntimePareto.mockReset().mockResolvedValue([BUCKET]);
  });

  // Spec test 5, the Stops half.
  it('says no OEE unit is configured, and asks for nothing', async () => {
    render(<StopsTab asset={LINE2} />);
    expect(await screen.findByText(/no oee unit is configured/i)).toBeInTheDocument();
    expect(screen.getByText(/conf\/oee\/units\.yaml/)).toBeInTheDocument();
    expect(getDowntimeEvents).not.toHaveBeenCalled();
    expect(getDowntimePareto).not.toHaveBeenCalled();
  });

  it('lists each stop with its duration, state, reason and source', async () => {
    render(<StopsTab asset={LINE1} />);
    const row = (await screen.findByText('STOPPED')).closest('tr')!;
    expect(row.textContent).toContain('0:19');
    expect(row.textContent).toContain('Unassigned');
    expect(row.textContent).toContain('Unplanned');
    expect(row.textContent).toContain('Automatic');
  });

  it('shows who attested a manual reason, and when', async () => {
    getDowntimeEvents.mockResolvedValue([
      { ...EVENT, reasonSource: 'MANUAL', assignedBy: 'shift.lead', assignedAt: '2026-09-02T09:00:00.000Z', note: 'seal failed' },
    ]);
    render(<StopsTab asset={LINE1} />);
    const badge = await screen.findByText(/by hand/i);
    expect(badge.getAttribute('title')).toContain('shift.lead');
    expect(badge.getAttribute('title')).toContain('2026-09-02');
    expect(screen.getByText('seal failed')).toBeInTheDocument();
  });

  it('renders the Pareto beside the list', async () => {
    render(<StopsTab asset={LINE1} />);
    expect(await screen.findByTestId('pareto-UNASSIGNED')).toBeInTheDocument();
  });

  it('opens the reassign dialog for the chosen stop and re-reads after it succeeds', async () => {
    render(<StopsTab asset={LINE1} />);
    await userEvent.click(await screen.findByRole('button', { name: /reassign/i }));
    expect(screen.getByText('reassigning 11')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'confirm' }));
    // The Pareto and the shift are both stale after a reassignment, so both reads run again.
    await waitFor(() => expect(getDowntimePareto).toHaveBeenCalledTimes(2));
    expect(getDowntimeEvents).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(await screen.findByText(/queued for recomputation/i)).toBeInTheDocument();
  });

  it('re-reads when the range changes', async () => {
    render(<StopsTab asset={LINE1} />);
    await screen.findByText('STOPPED');
    await userEvent.click(screen.getByRole('button', { name: '24h' }));
    await waitFor(() => expect(getDowntimeEvents).toHaveBeenCalledTimes(2));
  });

  it('explains an empty range', async () => {
    getDowntimeEvents.mockResolvedValue([]);
    getDowntimePareto.mockResolvedValue([]);
    render(<StopsTab asset={LINE1} />);
    expect(await screen.findByText(/no stops recorded/i)).toBeInTheDocument();
  });

  it('surfaces a failed read', async () => {
    getDowntimeEvents.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<StopsTab asset={LINE1} />);
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 10: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/StopsTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 11: Write `StopsTab`**

```tsx
import React, { useCallback, useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../../services/graphql/client';
import type { GraphqlAssetNode } from '../../../services/graphql/types';
import type { DowntimeEvent, DowntimeParetoBucket } from '../../../types/oee';
import { hasOeeUnit } from '../../../lib/oee/units';
import { formatDurationS } from '../../../lib/oee/format';
import { DataTable, type Column } from '../../common/DataTable';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill } from '../../common/StatusPill';
import { ParetoBars } from '../ParetoBars';
import { ReassignReasonDialog } from '../ReassignReasonDialog';

const RANGES: { label: string; days: number }[] = [
  { label: '24h', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
];

export const StopsTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const configured = hasOeeUnit(asset.path);
  const [days, setDays] = useState(7);
  const [events, setEvents] = useState<DowntimeEvent[] | null>(null);
  const [pareto, setPareto] = useState<DowntimeParetoBucket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reassigning, setReassigning] = useState<DowntimeEvent | null>(null);
  const [recomputed, setRecomputed] = useState<string | null>(null);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!configured) return;
    let cancelled = false;
    setError(null);
    const to = new Date();
    const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
    Promise.all([
      unsGraphQLClient.getDowntimeEvents(asset.path, from.toISOString(), to.toISOString()),
      unsGraphQLClient.getDowntimePareto(asset.path, from.toISOString(), to.toISOString()),
    ])
      .then(([loadedEvents, loadedPareto]) => {
        if (cancelled) return;
        setEvents(loadedEvents);
        setPareto(loadedPareto);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [asset.path, configured, days, reloads]);

  const onAssigned = useCallback((updated: DowntimeEvent) => {
    setReassigning(null);
    setRecomputed(updated.shiftStart);
    // Both reads are stale: the event's reason changed, and its seconds moved between
    // Pareto buckets. Patching the row locally would show a Pareto that no longer matches it.
    setReloads((count) => count + 1);
  }, []);

  const COLUMNS: Column<DowntimeEvent>[] = [
    { key: 'started', header: 'Started', mono: true, render: (e) => e.startedAt },
    { key: 'ended', header: 'Ended', mono: true, render: (e) => e.endedAt },
    { key: 'duration', header: 'Duration', align: 'right', render: (e) => formatDurationS(e.durationS) },
    { key: 'state', header: 'State', mono: true, render: (e) => e.stateValue },
    { key: 'reason', header: 'Reason', render: (e) => e.reasonDisplayName },
    { key: 'category', header: 'Category', render: (e) => e.reasonCategory },
    {
      key: 'planned',
      header: 'Counts as',
      render: (e) => (
        <StatusPill
          label={e.isPlanned ? 'Planned' : 'Unplanned'}
          tone={e.isPlanned ? 'neutral' : 'warn'}
          title={
            e.isPlanned
              ? 'Excluded from Unplanned Down, so it does not reduce Availability'
              : 'Counted as Unplanned Down, so it reduces Availability'
          }
        />
      ),
    },
    {
      key: 'source',
      header: 'Attribution',
      render: (e) =>
        e.reasonSource === 'MANUAL' ? (
          <StatusPill
            label="By hand"
            tone="info"
            title={`Attested by ${e.assignedBy ?? 'someone who gave no name'} at ${e.assignedAt ?? 'an unrecorded time'} — a claim, not an authenticated identity`}
          />
        ) : (
          <StatusPill label="Automatic" tone="neutral" title="Derived by the OEE engine from the published state value" />
        ),
    },
    { key: 'note', header: 'Note', render: (e) => e.note },
    {
      key: 'action',
      header: '',
      render: (e) => (
        <button
          type="button"
          onClick={() => setReassigning(e)}
          className="rounded px-1.5 py-0.5 text-[11px] text-sky-700 hover:bg-sky-500/10 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:text-sky-300"
        >
          Reassign
        </button>
      ),
    },
  ];

  if (!configured) {
    return (
      <EmptyState
        title="No OEE unit is configured for this Asset"
        detail="Stops are derived from the state Metric of an Asset declared in conf/oee/units.yaml. Adding this Asset there, and restarting the OEE service, is what makes this tab show stops."
      />
    );
  }
  if (error) return <EmptyState title="Could not read stops" detail={error} />;
  if (events === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading stops…</p>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-[#E2E8F0] px-2 py-1 dark:border-[#1E293B]">
        {RANGES.map((range) => (
          <button
            key={range.label}
            type="button"
            onClick={() => setDays(range.days)}
            aria-pressed={days === range.days}
            className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
              days === range.days
                ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
                : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
            }`}
          >
            {range.label}
          </button>
        ))}
        {recomputed && (
          <span className="ml-auto text-[11px] text-amber-700 dark:text-amber-300">
            Shift starting {recomputed} is queued for recomputation. Its OEE may change and will
            appear as a restated revision.
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <DataTable
            columns={COLUMNS}
            rows={events}
            rowKey={(event) => event.id}
            empty={
              <EmptyState
                title="No stops recorded in this range"
                detail="Either the line did not stop, or no shift covering this range has been computed yet. Stops appear once the shift they belong to closes."
              />
            }
          />
        </div>
        <div className="w-[300px] shrink-0 overflow-y-auto border-l border-[#E2E8F0] dark:border-[#1E293B]">
          <h3 className="px-3 pt-2 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
            Downtime by reason
          </h3>
          <ParetoBars buckets={pareto} />
        </div>
      </div>

      {reassigning && (
        <ReassignReasonDialog
          event={reassigning}
          onCancel={() => setReassigning(null)}
          onAssigned={onAssigned}
        />
      )}
    </div>
  );
};
```

- [ ] **Step 12: Run everything this task touches**

```bash
cd 11_frontend && npx vitest run src/components/plant src/lib/oee && npx tsc --noEmit && npm run lint
```

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add 11_frontend/src/components/plant/ParetoBars.tsx 11_frontend/src/components/plant/ParetoBars.test.tsx \
  11_frontend/src/components/plant/ReassignReasonDialog.tsx 11_frontend/src/components/plant/ReassignReasonDialog.test.tsx \
  11_frontend/src/components/plant/tabs/StopsTab.tsx 11_frontend/src/components/plant/tabs/StopsTab.test.tsx
git commit -m "feat(frontend): make the downtime reason reassignment usable and honest

The picker is fed by getDowntimeReasons rather than the Pareto, so a code authored in
conf/oee/reasons.yaml but never yet triggered is reachable - the reason that query was
added. The dialog says what the mutation actually does: it queues the shift for
recomputation, and a planned reason can change the OEE.

The name recorded is typed by the operator and labelled as unverified, because the
argument's own description says it is attested and not authenticated. The browser-local
AuthContext user is never sent, and a test asserts this component does not import it."
```

---

## Task 14: PLANT ▸ Alarms — which rules watch this Asset

The spec's tab table says this tab's data is `getAlertRules(topic:)`. Read `09_uns_model/src/uns_model/alert_rules.py:213-221` before writing it, because that argument cannot answer the question:

```python
if topic is not None:
    statement = statement.where(AlertRule.topic == topic)
```

Exact string equality. An Alert Rule watches a **Metric topic**, which is below the Asset — `.../Line1/Cell1/MES-01/Status/PackMlState`, or a wildcard like `.../Line1/#`. Neither is equal to `.../Line1`, so `getAlertRules(topic: asset.path)` would render an empty Alarms tab on an Asset that has rules on it. That is a worse untruth than the pages this plan is deleting.

So this tab answers the question in the browser instead: it takes the rules the console already holds and keeps the ones whose topic filter covers this Asset or anything below it. **Requires backend** to do better: a prefix- or wildcard-aware `topic:` filter on `list_rules` would let this be one narrow query. Out of scope here — the spec allows exactly one new read query and it is `getDowntimeReasons`.

Two more things this task settles:

**The matcher becomes one tested function.** `AlarmContext.tsx:650-655` matches topics inline with `rule.topic.endsWith('/#')`, `rule.topic.includes('/+')` and an unescaped `new RegExp`. It handles neither a `+` and a `#` in the same filter nor a filter containing regex metacharacters. Extracting it is not gold-plating: this tab needs the same logic, and two copies of a subtly wrong matcher is how an alarm silently stops firing. Task 20 replaces the inline version with this one.

**The tab does not issue a query at all.** `useAlarms()` already exposes `rules` loaded from `getAlertRules` and `activeAlarms`. Fetching again per Asset selection would double the reads and could show a rule list that disagrees with the ALARMS destination.

**Files:**
- Create: `11_frontend/src/lib/uns/topic-match.ts`
- Test: `11_frontend/src/lib/uns/topic-match.test.ts`
- Create: `11_frontend/src/components/alarms/BrowserEvaluationNotice.tsx`
- Modify: `11_frontend/src/components/plant/tabs/AlarmsTab.tsx`
- Test: `11_frontend/src/components/plant/tabs/AlarmsTab.test.tsx`

**Interfaces:**
- Consumes: `useAlarms()` from `src/context/AlarmContext.tsx` (`rules: AlertRule[]`, `activeAlarms: ActiveAlarm[]`, `rulesOrigin`, `rulesError`), `AlertRule`/`ActiveAlarm`/`AlarmSeverity` from `src/types/alarm.ts`, `DataTable`, `Column`, `StatusPill`, `EmptyState`.
- Produces:
  ```ts
  // src/lib/uns/topic-match.ts
  /** MQTT filter semantics: `+` is one level, `#` is the rest including its parent level. */
  export function topicMatchesFilter(filter: string, topic: string): boolean;
  /** Whether a filter can match this topic or any topic below it. */
  export function filterCoversSubtree(filter: string, topic: string): boolean;
  ```
  ```tsx
  export const BrowserEvaluationNotice: React.FC<{ className?: string }>;
  ```
  Task 20 uses `topicMatchesFilter` and `BrowserEvaluationNotice`; Task 17 uses neither.

- [ ] **Step 1: Write the failing matcher test**

Create `11_frontend/src/lib/uns/topic-match.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { filterCoversSubtree, topicMatchesFilter } from './topic-match';

const LINE = 'CovestroAG/Dormagen/Production/Line1';
const METRIC = `${LINE}/Cell1/MES-01/Status/PackMlState`;

describe('topicMatchesFilter', () => {
  it('matches an exact topic', () => {
    expect(topicMatchesFilter(METRIC, METRIC)).toBe(true);
    expect(topicMatchesFilter(LINE, METRIC)).toBe(false);
  });

  it('treats + as exactly one level', () => {
    expect(topicMatchesFilter(`${LINE}/+`, `${LINE}/Cell1`)).toBe(true);
    expect(topicMatchesFilter(`${LINE}/+`, `${LINE}/Cell1/MES-01`)).toBe(false);
    expect(topicMatchesFilter(`${LINE}/+`, LINE)).toBe(false);
  });

  it('treats # as the rest of the tree, including the parent level', () => {
    // MQTT: "sport/#" matches "sport". A rule on Line1/# watches Line1's own payload too.
    expect(topicMatchesFilter(`${LINE}/#`, LINE)).toBe(true);
    expect(topicMatchesFilter(`${LINE}/#`, METRIC)).toBe(true);
    expect(topicMatchesFilter(`${LINE}/#`, 'CovestroAG/Dormagen/Production/Line2/Cell1')).toBe(false);
  });

  it('handles a + and a # in the same filter, which the inline matcher did not', () => {
    expect(topicMatchesFilter('CovestroAG/+/Production/#', METRIC)).toBe(true);
    expect(topicMatchesFilter('CovestroAG/+/Packaging/#', METRIC)).toBe(false);
  });

  it('treats the console’s * as every topic', () => {
    // Not MQTT. It is what stored rules already use for "global", so it keeps working.
    expect(topicMatchesFilter('*', METRIC)).toBe(true);
  });

  it('does not let a regex metacharacter in a topic match anything', () => {
    expect(topicMatchesFilter('Plant/A.B', 'Plant/AxB')).toBe(false);
    expect(topicMatchesFilter('Plant/A.B', 'Plant/A.B')).toBe(true);
  });

  it('matches Sparkplug topics with the same rules', () => {
    expect(topicMatchesFilter('spBv1.0/#', 'spBv1.0/Dormagen/NDATA/Edge1/Line1')).toBe(true);
    expect(topicMatchesFilter('spBv1.0/#', METRIC)).toBe(false);
  });
});

describe('filterCoversSubtree', () => {
  it('covers when the filter is the topic itself', () => {
    expect(filterCoversSubtree(LINE, LINE)).toBe(true);
  });

  it('covers when the filter targets something below the topic', () => {
    expect(filterCoversSubtree(METRIC, LINE)).toBe(true);
    expect(filterCoversSubtree(`${LINE}/+`, LINE)).toBe(true);
    expect(filterCoversSubtree(`${LINE}/#`, LINE)).toBe(true);
  });

  it('covers when a wildcard above the topic reaches into it', () => {
    expect(filterCoversSubtree('CovestroAG/#', LINE)).toBe(true);
    expect(filterCoversSubtree('CovestroAG/+/Production/Line1', LINE)).toBe(true);
    expect(filterCoversSubtree('*', LINE)).toBe(true);
  });

  it('does not cover an ancestor-only filter', () => {
    // A rule on the Area's own payload is not a rule on this Line.
    expect(filterCoversSubtree('CovestroAG/Dormagen/Production', LINE)).toBe(false);
  });

  it('does not cover a sibling', () => {
    expect(filterCoversSubtree('CovestroAG/Dormagen/Production/Line2/#', LINE)).toBe(false);
    expect(filterCoversSubtree('CovestroAG/Dormagen/Packaging/+', LINE)).toBe(false);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/uns/topic-match.test.ts
```

Expected: FAIL — `Failed to resolve import "./topic-match"`.

- [ ] **Step 3: Write the matcher**

Create `11_frontend/src/lib/uns/topic-match.ts`:

```ts
/**
 * MQTT topic-filter matching, in one place.
 *
 * This is display and evaluation logic only: the console never subscribes with a filter it
 * built here. Tree expansion uses `childrenTopic` and a subtree read uses `subtreeTopic`.
 *
 * `*` is not MQTT. Stored Alert Rules use it to mean "every topic", so it is honoured rather
 * than silently failing to match.
 */

const GLOBAL = '*'

function segments(value: string): string[] {
  return value.split('/')
}

/**
 * Whether `topic` is one of the topics `filter` selects.
 *
 * `+` matches exactly one level. `#` matches the remaining levels and also the level it sits
 * under, so `a/b/#` matches `a/b` — that is the MQTT rule, and it is why a rule written as
 * `Line1/#` fires on Line1's own payload as well as its children's.
 */
export function topicMatchesFilter(filter: string, topic: string): boolean {
  if (filter === GLOBAL) return true
  if (filter === topic) return true

  const filterParts = segments(filter)
  const topicParts = segments(topic)

  for (let index = 0; index < filterParts.length; index += 1) {
    const part = filterParts[index]
    if (part === '#') {
      // `a/b/#` matches `a/b`, so the topic may end exactly here.
      return true
    }
    if (index >= topicParts.length) return false
    if (part !== '+' && part !== topicParts[index]) return false
  }
  // No wildcard consumed the tail, so the lengths have to agree.
  return filterParts.length === topicParts.length
}

/**
 * Whether `filter` can match `topic` or anything below it.
 *
 * This is the question the Alarms tab asks: does any rule watch this Asset? A rule on a
 * Metric five levels below the Asset does watch it. A rule on the Area above it does not.
 */
export function filterCoversSubtree(filter: string, topic: string): boolean {
  if (filter === GLOBAL) return true

  const filterParts = segments(filter)
  const topicParts = segments(topic)

  for (let index = 0; index < filterParts.length; index += 1) {
    const part = filterParts[index]
    if (part === '#') return true
    if (index >= topicParts.length) {
      // Every level of the topic matched and the filter keeps going, so the filter names a
      // descendant of the topic.
      return true
    }
    if (part !== '+' && part !== topicParts[index]) return false
  }
  // The filter ran out first. It is the topic itself, or an ancestor of it — and an
  // ancestor's own payload is not this Asset.
  return filterParts.length === topicParts.length
}
```

- [ ] **Step 4: Run the matcher tests**

```bash
cd 11_frontend && npx vitest run src/lib/uns/topic-match.test.ts && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 5: Write the failing Alarms tab test**

Create `11_frontend/src/components/plant/tabs/AlarmsTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ActiveAlarm, AlertRule } from '../../../types/alarm';

const useAlarms = vi.fn();
vi.mock('../../../context/AlarmContext', () => ({ useAlarms: () => useAlarms() }));

import { AlarmsTab } from './AlarmsTab';

const LINE1 = {
  path: 'CovestroAG/Dormagen/Production/Line1',
  segment: 'Line1',
  level: 'LINE',
  name: 'Line 1',
  isActive: true,
};

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'rule-1',
    name: 'Pack state stalled',
    description: 'PackMlState has not changed',
    enabled: true,
    severity: 'HIGH',
    category: 'STALE_TIMEOUT',
    topic: `${LINE1.path}/Cell1/MES-01/Status/PackMlState`,
    metricField: 'value',
    condition: 'STALE_TIMEOUT',
    thresholdValue: 600,
    unit: 's',
    targetRoles: ['operator'],
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: true,
      mqttPublishOnTrigger: false,
      emailWebhook: false,
    },
    triggerCount: 2,
    lastTriggeredAt: '2026-09-01T22:14:00.000Z',
    createdAt: '2026-08-01T00:00:00.000Z',
    updatedAt: '2026-08-01T00:00:00.000Z',
    ...overrides,
  };
}

function alarm(overrides: Partial<ActiveAlarm> = {}): ActiveAlarm {
  return {
    id: 'alm-1',
    ruleId: 'rule-1',
    ruleName: 'Pack state stalled',
    topic: `${LINE1.path}/Cell1/MES-01/Status/PackMlState`,
    severity: 'HIGH',
    category: 'STALE_TIMEOUT',
    conditionDescription: 'No change for 600 s',
    currentValue: 'IDLE',
    status: 'ACTIVE_UNACK',
    triggeredAt: '2026-09-02T11:40:00.000Z',
    targetRoles: ['operator'],
    ...overrides,
  };
}

function context(overrides: Record<string, unknown> = {}) {
  return {
    rules: [rule()],
    activeAlarms: [],
    rulesOrigin: 'server',
    rulesError: null,
    ...overrides,
  };
}

describe('AlarmsTab', () => {
  beforeEach(() => {
    useAlarms.mockReset().mockReturnValue(context());
  });

  it('lists a rule that watches a Metric below this Asset', () => {
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText('Pack state stalled')).toBeInTheDocument();
    expect(screen.getByText(/STALE_TIMEOUT/)).toBeInTheDocument();
  });

  it('lists a rule whose wildcard reaches into this Asset', () => {
    useAlarms.mockReturnValue(context({ rules: [rule({ topic: 'CovestroAG/#', name: 'Everything' })] }));
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText('Everything')).toBeInTheDocument();
  });

  it('leaves out a rule on a sibling line', () => {
    useAlarms.mockReturnValue(
      context({ rules: [rule({ topic: 'CovestroAG/Dormagen/Production/Line2/#', name: 'Line 2 only' })] }),
    );
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.queryByText('Line 2 only')).not.toBeInTheDocument();
    expect(screen.getByText(/no alert rule watches this asset/i)).toBeInTheDocument();
  });

  it('marks a disarmed rule so it is not read as protection', () => {
    useAlarms.mockReturnValue(context({ rules: [rule({ enabled: false })] }));
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText(/disarmed/i)).toBeInTheDocument();
  });

  it('shows the condition as a sentence with the threshold and unit', () => {
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText(/value has not changed for 600 s/i)).toBeInTheDocument();
  });

  it('renders a comparison rule’s condition with its operator', () => {
    useAlarms.mockReturnValue(
      context({ rules: [rule({ condition: 'GREATER_THAN', metricField: 'value', thresholdValue: 95, unit: '°C' })] }),
    );
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText(/value above 95 °C/i)).toBeInTheDocument();
  });

  it('lists an active alarm on this Asset above the rules', () => {
    useAlarms.mockReturnValue(context({ activeAlarms: [alarm()] }));
    render(<AlarmsTab asset={LINE1} />);
    const active = screen.getByTestId('active-alarms');
    expect(active.textContent).toContain('No change for 600 s');
    expect(active.textContent).toContain('Unacknowledged');
  });

  it('ignores an active alarm on another Asset', () => {
    useAlarms.mockReturnValue(
      context({ activeAlarms: [alarm({ topic: 'CovestroAG/Dormagen/Production/Line2/x' })] }),
    );
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.queryByTestId('active-alarms')).not.toBeInTheDocument();
  });

  it('states that evaluation happens in this browser', () => {
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText(/evaluated in this browser/i)).toBeInTheDocument();
  });

  it('surfaces a rules load failure instead of implying there are no rules', () => {
    useAlarms.mockReturnValue(context({ rules: [], rulesError: 'GraphQL endpoint unreachable' }));
    render(<AlarmsTab asset={LINE1} />);
    expect(screen.getByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
    expect(screen.queryByText(/no alert rule watches this asset/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/plant/tabs/AlarmsTab.test.tsx
```

Expected: FAIL — the Task 8 placeholder renders none of this.

- [ ] **Step 7: Write the browser-evaluation notice**

Create `11_frontend/src/components/alarms/BrowserEvaluationNotice.tsx`:

```tsx
import React from 'react';

/**
 * The single sentence that keeps the alarm surfaces truthful.
 *
 * Alert Rules are stored in Postgres and shared, so what a rule says is real. Evaluation is
 * not: AlarmContext compares live MQTT messages in this tab, so an alarm exists only while
 * somebody has the console open, and two open tabs each have their own alarm list. Anyone
 * treating this as a plant alarm system needs to know that before they rely on it.
 */
export const BrowserEvaluationNotice: React.FC<{ className?: string }> = ({ className = '' }) => (
  <p className={`text-[11px] text-[#64748B] ${className}`}>
    Rules are stored on the server and shared. Conditions are evaluated in this browser from
    the live feed, so an alarm exists only while the console is open and is not a plant alarm
    system.
  </p>
);
```

- [ ] **Step 8: Write `AlarmsTab`**

```tsx
import React, { useMemo } from 'react';
import { useAlarms } from '../../../context/AlarmContext';
import type { GraphqlAssetNode } from '../../../services/graphql/types';
import type { ActiveAlarm, AlarmSeverity, AlertRule } from '../../../types/alarm';
import { filterCoversSubtree, topicMatchesFilter } from '../../../lib/uns/topic-match';
import { DataTable, type Column } from '../../common/DataTable';
import { EmptyState } from '../../common/EmptyState';
import { StatusPill, type PillTone } from '../../common/StatusPill';
import { BrowserEvaluationNotice } from '../../alarms/BrowserEvaluationNotice';

const SEVERITY_TONE: Record<AlarmSeverity, PillTone> = {
  CRITICAL: 'bad',
  HIGH: 'bad',
  WARNING: 'warn',
  INFO: 'info',
};

const STATUS_TEXT: Record<ActiveAlarm['status'], string> = {
  ACTIVE_UNACK: 'Unacknowledged',
  ACTIVE_ACK: 'Acknowledged',
  CLEARED_UNACK: 'Cleared, unacknowledged',
  RESOLVED: 'Resolved',
};

/**
 * The rule's condition as a sentence.
 *
 * The stored fields are a field name, an operator enum, a threshold and a unit the engineer
 * typed. Rendering the enum would make an operator translate GREATER_THAN in their head.
 */
function conditionSentence(rule: AlertRule): string {
  const unit = rule.unit ? ` ${rule.unit}` : '';
  const value = `${String(rule.thresholdValue)}${unit}`;
  switch (rule.condition) {
    case 'GREATER_THAN':
      return `${rule.metricField} above ${value}`;
    case 'LESS_THAN':
      return `${rule.metricField} below ${value}`;
    case 'EQUALS':
      return `${rule.metricField} equals ${value}`;
    case 'NOT_EQUALS':
      return `${rule.metricField} is anything but ${value}`;
    case 'RANGE_OUTSIDE':
      return `${rule.metricField} outside ${String(rule.thresholdValue)} to ${
        rule.thresholdUpperValue ?? '?'
      }${unit}`;
    case 'STALE_TIMEOUT':
      return `${rule.metricField} has not changed for ${value}`;
    case 'CONTAINS':
      return `${rule.metricField} contains ${value}`;
    default:
      return `${rule.metricField} ${rule.condition} ${value}`;
  }
}

const RULE_COLUMNS: Column<AlertRule>[] = [
  { key: 'name', header: 'Rule', render: (r) => r.name },
  {
    key: 'severity',
    header: 'Severity',
    render: (r) => <StatusPill label={r.severity} tone={SEVERITY_TONE[r.severity]} />,
  },
  { key: 'category', header: 'Category', render: (r) => r.category },
  { key: 'topic', header: 'Watches', mono: true, render: (r) => r.topic },
  { key: 'condition', header: 'Condition', render: conditionSentence },
  {
    key: 'armed',
    header: 'Armed',
    render: (r) =>
      r.enabled ? (
        <StatusPill label="Armed" tone="good" />
      ) : (
        <StatusPill label="Disarmed" tone="neutral" title="This rule is stored but will not fire" />
      ),
  },
  {
    key: 'lastTriggered',
    header: 'Last fired',
    mono: true,
    render: (r) => r.lastTriggeredAt ?? 'never',
  },
  { key: 'count', header: 'Fired', align: 'right', render: (r) => r.triggerCount.toLocaleString() },
];

const ALARM_COLUMNS: Column<ActiveAlarm>[] = [
  { key: 'triggered', header: 'Since', mono: true, render: (a) => a.triggeredAt },
  {
    key: 'severity',
    header: 'Severity',
    render: (a) => <StatusPill label={a.severity} tone={SEVERITY_TONE[a.severity]} />,
  },
  { key: 'rule', header: 'Rule', render: (a) => a.ruleName },
  { key: 'topic', header: 'Topic', mono: true, render: (a) => a.topic },
  { key: 'condition', header: 'Condition', render: (a) => a.conditionDescription },
  { key: 'value', header: 'Value', mono: true, render: (a) => String(a.currentValue) },
  { key: 'status', header: 'Status', render: (a) => STATUS_TEXT[a.status] },
];

export const AlarmsTab: React.FC<{ asset: GraphqlAssetNode }> = ({ asset }) => {
  const { rules, activeAlarms, rulesError } = useAlarms();

  // The server's topic: argument is exact equality (alert_rules.py:219), so the question
  // "which rules watch this Asset?" is answered here instead.
  const watching = useMemo(
    () => rules.filter((rule) => filterCoversSubtree(rule.topic, asset.path)),
    [rules, asset.path],
  );

  const alarmsHere = useMemo(
    () =>
      activeAlarms.filter(
        (alarm) =>
          alarm.topic === asset.path ||
          alarm.topic.startsWith(`${asset.path}/`) ||
          topicMatchesFilter(alarm.topic, asset.path),
      ),
    [activeAlarms, asset.path],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-[#E2E8F0] px-3 py-1.5 dark:border-[#1E293B]">
        <BrowserEvaluationNotice />
      </div>

      {alarmsHere.length > 0 && (
        <div data-testid="active-alarms" className="max-h-[45%] shrink-0 overflow-y-auto border-b border-[#E2E8F0] dark:border-[#1E293B]">
          <h3 className="px-3 pt-2 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
            Standing alarms
          </h3>
          <DataTable
            columns={ALARM_COLUMNS}
            rows={alarmsHere}
            rowKey={(alarm) => alarm.id}
            empty={null}
          />
        </div>
      )}

      <div className="min-h-0 flex-1">
        <h3 className="px-3 pt-2 text-[11px] font-bold uppercase tracking-widest text-[#64748B]">
          Rules watching this Asset
        </h3>
        {rulesError ? (
          <EmptyState title="Could not read the Alert Rules" detail={rulesError} />
        ) : (
          <DataTable
            columns={RULE_COLUMNS}
            rows={watching}
            rowKey={(rule) => rule.id}
            empty={
              <EmptyState
                title="No Alert Rule watches this Asset"
                detail="A rule watches this Asset when its topic is this Asset, a Metric below it, or a wildcard covering it. Author one on the Alarms destination."
              />
            }
          />
        )}
      </div>
    </div>
  );
};
```

`DataTable`'s `empty` prop is required, and `null` is passed for the standing-alarms table because that block only renders when there is at least one row. If Task 5's `DataTable` types `empty` as `React.ReactNode`, `null` is valid; if it typed it as `React.ReactElement`, widen it to `React.ReactNode` in `DataTable.tsx` rather than inventing an empty state that can never appear.

- [ ] **Step 9: Run the tests**

```bash
cd 11_frontend && npx vitest run src/components/plant src/lib/uns && npx tsc --noEmit && npm run lint
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add 11_frontend/src/lib/uns/topic-match.ts 11_frontend/src/lib/uns/topic-match.test.ts \
  11_frontend/src/components/alarms/BrowserEvaluationNotice.tsx \
  11_frontend/src/components/plant/tabs/AlarmsTab.tsx 11_frontend/src/components/plant/tabs/AlarmsTab.test.tsx
git commit -m "feat(frontend): show which Alert Rules actually watch the selected Asset

getAlertRules(topic:) filters by exact string equality (alert_rules.py:219), and rules
watch Metric topics below an Asset, so asking the server for the Asset path would have
rendered an empty tab on an Asset that has rules. The filtering happens here instead,
against the rules the console already holds.

MQTT filter matching becomes one tested function. The inline version in AlarmContext
mishandles a filter with both + and #, and builds an unescaped RegExp from a topic.

Every alarm surface now carries one sentence: rules are shared, but evaluation happens
in this browser, so an alarm exists only while the console is open."
```

---

## Task 15: SHIFT — the destination a shift lead opens

Spec section 9's last paragraph: "`/shift` exists so a shift lead does not have to navigate a plant tree to find the one line that has OEE." Spec section 14: `uns-oee` is embedded here, with `var-asset`.

Two repo facts:

1. **`uns-oee` defines exactly one variable, `asset`**, and its query is `SELECT a.path FROM model.oee_unit u JOIN model.asset a ON a.id = u.asset_id WHERE u.is_active ORDER BY 1` (`08_uns_observability/grafana/dashboards/oee.json`). That is the same set `OEE_UNIT_PATHS` mirrors — `conf/oee/units.yaml` is what seeds `model.oee_unit`. So the constant introduced in Task 12 and the dashboard's dropdown are two views of one authored list, which is the strongest argument available that the constant is not a fabrication.
2. **`getAsset(path)` is already reachable.** The field exists (`07_uns_graphql/src/uns_graphql/queries/asset.py:89`, "One Asset by its path, or null when nothing is modelled at that path") and the foundation plan's Task 8 exposes it as `client.getAsset(path)`. This task adds no query and no client method — if `getAsset` is missing when you start, the foundation plan was not finished and this task is blocked.

This destination composes what already exists: the `uns-oee` embed, then `ShiftOeeTab` and `StopsTab` on the configured unit. Rebuilding either would put a second definition of "null is not zero" in the codebase.

**Files:**
- Create: `11_frontend/src/components/shift/ShiftView.tsx`
- Test: `11_frontend/src/components/shift/ShiftView.test.tsx`
- Modify: `11_frontend/src/App.tsx` (point `/shift` at `ShiftView`)
- Modify: `11_frontend/src/App.routes.test.tsx` (one line in the client mock)

**Interfaces:**
- Consumes: `client.getAsset(path: string): Promise<GraphqlAssetNode | null>` (foundation Task 8), `OEE_UNIT_PATHS` (Task 12), `ShiftOeeTab` (Task 12), `StopsTab` (Task 13), `GrafanaEmbed` (Task 6), `useTheme`, `EmptyState`.
- Produces: `export const ShiftView: React.FC`.

- [ ] **Step 1: Confirm `getAsset` throws rather than returning null on a failed read**

```bash
cd 11_frontend && grep -n "public async getAsset" -A 10 src/services/graphql/client.ts
```

Expected: the method exists and raises on `res.error`. This view distinguishes "no Asset is modelled at that path" from "the read failed", and it can only do so if the client keeps them apart. If `getAsset` swallows errors into `null`, fix it there — with a test in `client-assets.test.ts` — before continuing, because a misconfiguration message shown during an outage is exactly the kind of confident wrong answer this console is being rebuilt to remove.

- [ ] **Step 2: Write the failing view test**

Create `11_frontend/src/components/shift/ShiftView.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAsset = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getAsset: (...args: unknown[]) => getAsset(...args) },
}));

vi.mock('../../lib/oee/units', () => ({
  OEE_UNIT_PATHS: ['CovestroAG/Dormagen/Production/Line1'],
  hasOeeUnit: (path: string) => path === 'CovestroAG/Dormagen/Production/Line1',
}));

vi.mock('../../context/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark', isDark: true }) }));

vi.mock('../plant/tabs/ShiftOeeTab', () => ({
  ShiftOeeTab: ({ asset }: { asset: { path: string } }) => <div>shift table for {asset.path}</div>,
}));
vi.mock('../plant/tabs/StopsTab', () => ({
  StopsTab: ({ asset }: { asset: { path: string } }) => <div>stops for {asset.path}</div>,
}));

import { ShiftView } from './ShiftView';

const LINE1 = {
  path: 'CovestroAG/Dormagen/Production/Line1',
  segment: 'Line1',
  level: 'LINE',
  name: 'Line 1',
  description: null,
  manufacturer: null,
  modelNumber: null,
  serialNumber: null,
  criticality: 'HIGH',
  isActive: true,
  attributes: { data: {} },
};

describe('ShiftView', () => {
  beforeEach(() => {
    getAsset.mockReset().mockResolvedValue(LINE1);
  });

  it('opens on the configured unit without any navigation', async () => {
    render(<ShiftView />);
    expect(await screen.findByText(`shift table for ${LINE1.path}`)).toBeInTheDocument();
    expect(screen.getByText(`stops for ${LINE1.path}`)).toBeInTheDocument();
    expect(getAsset).toHaveBeenCalledWith(LINE1.path);
  });

  it('embeds the OEE dashboard for that unit', async () => {
    render(<ShiftView />);
    const frame = (await screen.findByTitle(/oee/i)) as HTMLIFrameElement;
    expect(frame.src).toContain('/grafana/d/uns-oee');
    expect(frame.src).toContain(`var-asset=${encodeURIComponent(LINE1.path)}`);
    expect(frame.src).toContain('theme=dark');
  });

  it('says the Asset Model does not contain a configured unit, and does not render tabs', async () => {
    getAsset.mockResolvedValue(null);
    render(<ShiftView />);
    expect(await screen.findByText(/configured for oee but not in the asset model/i)).toBeInTheDocument();
    expect(screen.queryByText(/shift table for/)).not.toBeInTheDocument();
  });

  it('surfaces a failed read', async () => {
    getAsset.mockRejectedValue(new Error('Asset Model database unavailable'));
    render(<ShiftView />);
    expect(await screen.findByText(/Asset Model database unavailable/)).toBeInTheDocument();
  });

  it('offers no unit picker when only one unit is configured', async () => {
    render(<ShiftView />);
    await screen.findByText(`shift table for ${LINE1.path}`);
    expect(screen.queryByLabelText(/unit/i)).not.toBeInTheDocument();
  });

  it('switches unit when more than one is configured', async () => {
    const LINE2 = { ...LINE1, path: 'CovestroAG/Dormagen/Production/Line2', segment: 'Line2' };
    vi.doMock('../../lib/oee/units', () => ({
      OEE_UNIT_PATHS: [LINE1.path, LINE2.path],
      hasOeeUnit: () => true,
    }));
    vi.resetModules();
    const { ShiftView: MultiUnitView } = await import('./ShiftView');
    getAsset.mockImplementation((path: string) => Promise.resolve(path === LINE2.path ? LINE2 : LINE1));

    render(<MultiUnitView />);
    await screen.findByText(`shift table for ${LINE1.path}`);
    await userEvent.selectOptions(screen.getByLabelText(/unit/i), LINE2.path);
    expect(await screen.findByText(`shift table for ${LINE2.path}`)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/shift/ShiftView.test.tsx
```

Expected: FAIL — `Failed to resolve import "./ShiftView"`.

- [ ] **Step 4: Write `ShiftView`**

```tsx
import React, { useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetNode } from '../../services/graphql/types';
import { OEE_UNIT_PATHS } from '../../lib/oee/units';
import { useTheme } from '../../context/ThemeContext';
import { GrafanaEmbed } from '../common/GrafanaEmbed';
import { EmptyState } from '../common/EmptyState';
import { ShiftOeeTab } from '../plant/tabs/ShiftOeeTab';
import { StopsTab } from '../plant/tabs/StopsTab';

type Section = 'shifts' | 'stops';

/**
 * The shift lead's destination: the one line that has OEE, without a plant tree.
 *
 * The Asset is read with getAsset rather than assembled from the path, because the tabs need
 * the real AssetNode and because a unit configured in conf/oee/units.yaml but missing from
 * the Asset Model is a real misconfiguration that should be shown, not papered over.
 */
export const ShiftView: React.FC = () => {
  const { theme } = useTheme();
  const [path, setPath] = useState(OEE_UNIT_PATHS[0] ?? '');
  const [asset, setAsset] = useState<GraphqlAssetNode | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>('shifts');

  useEffect(() => {
    if (path === '') return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    unsGraphQLClient
      .getAsset(path)
      .then((found) => {
        if (cancelled) return;
        setAsset(found);
        setLoaded(true);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (OEE_UNIT_PATHS.length === 0) {
    return (
      <EmptyState
        title="No OEE unit is configured"
        detail="OEE is computed only for Assets declared in conf/oee/units.yaml. Declare one, with a shift pattern and rated cycle times, and restart the OEE service."
      />
    );
  }
  if (error) return <EmptyState title="Could not read the unit's Asset" detail={error} />;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="shift-view">
      <div className="flex shrink-0 items-center gap-3 border-b border-[#E2E8F0] px-3 py-1.5 dark:border-[#1E293B]">
        <h1 className="text-[13px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">Shift</h1>
        {OEE_UNIT_PATHS.length > 1 && (
          <>
            <label htmlFor="shift-unit" className="text-[11px] text-[#64748B]">
              Unit
            </label>
            <select
              id="shift-unit"
              value={path}
              onChange={(changeEvent) => setPath(changeEvent.target.value)}
              className="rounded border border-[#CBD5E1] bg-transparent px-2 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
            >
              {OEE_UNIT_PATHS.map((unit) => (
                <option key={unit} value={unit}>
                  {unit}
                </option>
              ))}
            </select>
          </>
        )}
        <span className="font-mono text-[11px] text-[#64748B]">{path}</span>
      </div>

      <div className="h-[38%] shrink-0 border-b border-[#E2E8F0] dark:border-[#1E293B]">
        <GrafanaEmbed
          uid="uns-oee"
          title={`OEE — ${path}`}
          variables={{ asset: path }}
          theme={theme}
        />
      </div>

      {!loaded ? (
        <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading the unit's Asset…</p>
      ) : asset === null ? (
        <EmptyState
          title="This unit is configured for OEE but not in the Asset Model"
          detail={`conf/oee/units.yaml declares ${path}, and no Asset is modelled at that path. The shift table and stop list need the Asset, so model it or correct the path.`}
        />
      ) : (
        <>
          <div className="flex shrink-0 gap-1 border-b border-[#E2E8F0] px-2 py-1 dark:border-[#1E293B]">
            {(['shifts', 'stops'] as Section[]).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setSection(id)}
                aria-pressed={section === id}
                className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                  section === id
                    ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
                    : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
                }`}
              >
                {id === 'shifts' ? 'Shifts' : 'Stops'}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {section === 'shifts' ? <ShiftOeeTab asset={asset} /> : <StopsTab asset={asset} />}
          </div>
        </>
      )}
    </div>
  );
};
```

Both sections are mounted one at a time rather than stacked, because the stop list and the shift table each want the full width of a dense table and stacking them would put two scrolling panes inside a pane.

- [ ] **Step 5: Point the route at it**

In `11_frontend/src/App.tsx`, replace the Task 1 placeholder for `/shift` with `<ShiftView />` and import it. Leave the other placeholders alone.

- [ ] **Step 6: Run the tests**

```bash
cd 11_frontend && npx vitest run src/components/shift src/services/graphql src/App.routes.test.tsx && npx tsc --noEmit && npm run lint
```

Expected: PASS. `App.routes.test.tsx` mocks the client module wholesale, so add `getAsset: vi.fn().mockResolvedValue(null)` to that mock — the route test asserts the route resolves, not that the shift data loads.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/components/shift/ 11_frontend/src/App.tsx 11_frontend/src/App.routes.test.tsx
git commit -m "feat(frontend): give the shift lead a destination that opens on the OEE unit

/shift reads the configured unit's Asset with the existing getAsset client method,
embeds uns-oee with var-asset - the one variable that dashboard defines - and reuses the
Shift and Stops tabs so 'null is not zero' has exactly one implementation.

A unit declared in conf/oee/units.yaml with no Asset modelled at that path is shown as
the misconfiguration it is, rather than as an empty shift table."
```

---

## Task 16: ASSETS — the authored model and what it does not cover

Spec test 11 lives here. Spec section 16's integration-engineer path is the whole design: "ASSETS → the completeness header shows the Unmodelled Topic count → click it → the worklist."

Facts to build on, not around:

- `getAssetModelSummary` returns `assets`, `metricDefinitions`, `boundTopics`, `unmodelledTopics` (`07_uns_graphql/src/uns_graphql/type/asset.py:137-143`). The last one's own description says "Non-zero means the model is incomplete."
- The foundation plan's `getAssetModelSummary()` returns `null` when the read fails. So `null` must render as "could not read", never as zeros — four zeros would say the plant has no Asset Model, which is a different and much worse claim than "the query failed".
- `getUnmodelledTopics(limit)` defaults to `DEFAULT_UNMODELLED_LIMIT = 100` (`queries/asset.py:37`). A truncated list beside an untruncated count would read as a shorter worklist than the plant has, so the list discloses the truncation using the count from the summary.
- Assets are seeded from `conf/settings.yaml`'s `simulator.*` section — `uns_model_seed --from-simulator-config`, and `docker compose up asset_model_setup` is what applies an edit (`09_uns_model/README.md:145-151`, `src/uns_model/cli.py:111`). That is what the empty states name, because "add an Asset" is not an action anywhere in this UI.

**Deviation from the spec's file list, deliberate:** section 17 lists `assets/AssetDetail`. There is no `AssetDetail` in this task, because `ModelTab` (Task 9) already renders exactly what the spec's Asset detail describes — level, description, manufacturer, model number, serial number, criticality, and the applicable Metric Definitions with their engineering range. A second component would be a second place for "an unauthored field renders as `—`" to be got wrong. `AuthoredAssetTree` is likewise `AssetTreeRail` (Task 8), which already reads `getAssets` and nests locally.

**Files:**
- Create: `11_frontend/src/components/assets/ModelSummaryHeader.tsx`
- Test: `11_frontend/src/components/assets/ModelSummaryHeader.test.tsx`
- Create: `11_frontend/src/components/assets/UnmodelledTopicsList.tsx`
- Test: `11_frontend/src/components/assets/UnmodelledTopicsList.test.tsx`
- Create: `11_frontend/src/components/assets/AssetsView.tsx`
- Test: `11_frontend/src/components/assets/AssetsView.test.tsx`
- Modify: `11_frontend/src/App.tsx` (point `/assets` at `AssetsView`)

**Interfaces:**
- Consumes: `client.getAssetModelSummary()`, `client.getUnmodelledTopics(limit?)` (foundation Task 8), `AssetModelSummary`, `AssetTreeRail` (Task 8), `ModelTab` (Task 9), `EmptyState`, `DataTable`, `Column`, `StatusPill`.
- Produces:
  ```tsx
  export const ModelSummaryHeader: React.FC<{
    summary: AssetModelSummary | null;
    error: string | null;
    onShowUnmodelled: () => void;
    showingUnmodelled: boolean;
  }>;

  export const UnmodelledTopicsList: React.FC<{ total: number | null }>;
  export const AssetsView: React.FC;
  ```
  Nothing later in this plan consumes these.

- [ ] **Step 1: Write the failing header test**

Create `11_frontend/src/components/assets/ModelSummaryHeader.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ModelSummaryHeader } from './ModelSummaryHeader';

const SUMMARY = { assets: 42, metricDefinitions: 118, boundTopics: 610, unmodelledTopics: 7 };

const props = {
  summary: SUMMARY,
  error: null,
  onShowUnmodelled: vi.fn(),
  showingUnmodelled: false,
};

describe('ModelSummaryHeader', () => {
  // Spec test 11, the count half.
  it('renders each count from the summary', () => {
    render(<ModelSummaryHeader {...props} />);
    expect(screen.getByTestId('count-assets').textContent).toContain('42');
    expect(screen.getByTestId('count-metricDefinitions').textContent).toContain('118');
    expect(screen.getByTestId('count-boundTopics').textContent).toContain('610');
    expect(screen.getByTestId('count-unmodelledTopics').textContent).toContain('7');
  });

  it('makes the Unmodelled count the way into the worklist', async () => {
    const onShowUnmodelled = vi.fn();
    render(<ModelSummaryHeader {...props} onShowUnmodelled={onShowUnmodelled} />);
    await userEvent.click(screen.getByRole('button', { name: /unmodelled/i }));
    expect(onShowUnmodelled).toHaveBeenCalledTimes(1);
  });

  it('says the model is complete when nothing is unmodelled', () => {
    render(<ModelSummaryHeader {...props} summary={{ ...SUMMARY, unmodelledTopics: 0 }} />);
    expect(screen.getByText(/every published topic matches an asset/i)).toBeInTheDocument();
  });

  it('does not render zeros when the summary could not be read', () => {
    // Four zeros would claim the plant has no Asset Model. A failed read is a different fact.
    render(<ModelSummaryHeader {...props} summary={null} error="GraphQL endpoint unreachable" />);
    expect(screen.getByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
    expect(screen.queryByTestId('count-assets')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('waits quietly while the summary loads', () => {
    render(<ModelSummaryHeader {...props} summary={null} error={null} />);
    expect(screen.getByText(/reading the asset model/i)).toBeInTheDocument();
    expect(screen.queryByTestId('count-assets')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/assets/ModelSummaryHeader.test.tsx
```

Expected: FAIL — `Failed to resolve import "./ModelSummaryHeader"`.

- [ ] **Step 3: Write `ModelSummaryHeader`**

```tsx
import React from 'react';
import type { AssetModelSummary } from '../../services/graphql/types';

interface Props {
  summary: AssetModelSummary | null;
  error: string | null;
  onShowUnmodelled: () => void;
  showingUnmodelled: boolean;
}

const COUNTS: { key: keyof AssetModelSummary; label: string; title: string }[] = [
  { key: 'assets', label: 'Assets', title: 'Assets authored in the Asset Model' },
  {
    key: 'metricDefinitions',
    label: 'Metric Definitions',
    title: 'Metric Definitions authored against those Assets',
  },
  {
    key: 'boundTopics',
    label: 'Bound topics',
    title: 'Published topics that resolve to an Asset',
  },
];

/**
 * How complete the Asset Model is.
 *
 * A null summary is a failed read, not an empty model: the client returns null when the
 * query errors, and rendering four zeros would tell an integration engineer the plant has no
 * Asset Model at all.
 */
export const ModelSummaryHeader: React.FC<Props> = ({
  summary,
  error,
  onShowUnmodelled,
  showingUnmodelled,
}) => {
  if (error) {
    return (
      <div className="border-b border-[#E2E8F0] px-3 py-2 text-[12px] text-red-600 dark:border-[#1E293B] dark:text-red-400">
        Could not read the Asset Model summary: {error}
      </div>
    );
  }
  if (summary === null) {
    return (
      <div className="border-b border-[#E2E8F0] px-3 py-2 text-[12px] text-[#64748B] dark:border-[#1E293B]">
        Reading the Asset Model…
      </div>
    );
  }

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-4 border-b border-[#E2E8F0] px-3 py-2 dark:border-[#1E293B]">
      <h1 className="text-[13px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">Assets</h1>
      {COUNTS.map((count) => (
        <span key={count.key} data-testid={`count-${count.key}`} title={count.title} className="text-[11px] text-[#64748B]">
          <span className="tabular-nums text-[13px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">
            {summary[count.key].toLocaleString()}
          </span>{' '}
          {count.label}
        </span>
      ))}

      <button
        type="button"
        onClick={onShowUnmodelled}
        aria-pressed={showingUnmodelled}
        data-testid="count-unmodelledTopics"
        title="Topics that have published data but match no Asset. Non-zero means the model is incomplete."
        className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
          summary.unmodelledTopics > 0
            ? 'bg-amber-500/15 text-amber-800 dark:text-amber-300'
            : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
        }`}
      >
        <span className="tabular-nums text-[13px] font-bold">
          {summary.unmodelledTopics.toLocaleString()}
        </span>{' '}
        Unmodelled Topics
      </button>

      {summary.unmodelledTopics === 0 && (
        <span className="text-[11px] text-emerald-700 dark:text-emerald-400">
          Every published topic matches an Asset.
        </span>
      )}
    </div>
  );
};
```

If `AssetModelSummary` is not exported from `src/services/graphql/types.ts` by foundation Task 8, import it from wherever that task put it rather than redeclaring the shape.

- [ ] **Step 4: Write the failing worklist test**

Create `11_frontend/src/components/assets/UnmodelledTopicsList.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getUnmodelledTopics = vi.fn();
vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getUnmodelledTopics: (...args: unknown[]) => getUnmodelledTopics(...args) },
}));

import { UnmodelledTopicsList } from './UnmodelledTopicsList';

const TOPICS = [
  'spBv1.0/CovestroAG/NBIRTH/GW1',
  'CovestroAG/Dormagen/Production/Line9/Cell1',
  'CovestroAG/Dormagen/Utilities/Chiller_02/temperature',
];

describe('UnmodelledTopicsList', () => {
  beforeEach(() => {
    getUnmodelledTopics.mockReset().mockResolvedValue(TOPICS);
  });

  // Spec test 11, the list half.
  it('lists every unmodelled topic', async () => {
    render(<UnmodelledTopicsList total={3} />);
    for (const topic of TOPICS) {
      expect(await screen.findByText(topic)).toBeInTheDocument();
    }
  });

  // Spec test 11, the complete-model half.
  it('says the model is complete on an empty list', async () => {
    getUnmodelledTopics.mockResolvedValue([]);
    render(<UnmodelledTopicsList total={0} />);
    expect(await screen.findByText(/every published topic matches an asset/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('discloses truncation instead of implying a shorter worklist', async () => {
    render(<UnmodelledTopicsList total={412} />);
    await screen.findByText(TOPICS[0]);
    expect(screen.getByTestId('unmodelled-truncated').textContent).toMatch(/3 of 412/);
  });

  it('says nothing about truncation when the list is whole', async () => {
    render(<UnmodelledTopicsList total={3} />);
    await screen.findByText(TOPICS[0]);
    expect(screen.queryByTestId('unmodelled-truncated')).not.toBeInTheDocument();
  });

  it('filters the list without hiding that it is filtered', async () => {
    render(<UnmodelledTopicsList total={3} />);
    await screen.findByText(TOPICS[0]);
    await userEvent.type(screen.getByLabelText(/filter/i), 'Chiller');
    expect(screen.getByText(TOPICS[2])).toBeInTheDocument();
    expect(screen.queryByText(TOPICS[0])).not.toBeInTheDocument();
    expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument();
  });

  it('marks a Sparkplug topic, which is not modelled by design', async () => {
    render(<UnmodelledTopicsList total={3} />);
    const row = (await screen.findByText(TOPICS[0])).closest('tr')!;
    expect(row.textContent).toContain('Sparkplug');
  });

  it('names where an Asset is authored', async () => {
    render(<UnmodelledTopicsList total={3} />);
    await screen.findByText(TOPICS[0]);
    expect(screen.getByText(/conf\/settings\.yaml/)).toBeInTheDocument();
    expect(screen.getByText(/asset_model_setup/)).toBeInTheDocument();
  });

  it('surfaces a failed read', async () => {
    getUnmodelledTopics.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<UnmodelledTopicsList total={3} />);
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/assets/UnmodelledTopicsList.test.tsx
```

Expected: FAIL — `Failed to resolve import "./UnmodelledTopicsList"`.

- [ ] **Step 6: Write `UnmodelledTopicsList`**

```tsx
import React, { useEffect, useMemo, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import { DataTable, type Column } from '../common/DataTable';
import { EmptyState } from '../common/EmptyState';
import { StatusPill } from '../common/StatusPill';

/** The server's own default. Asking for more would need a schema argument change. */
const LIMIT = 100;

const SPARKPLUG_PREFIX = 'spBv1.0/';

interface Row {
  topic: string;
  sparkplug: boolean;
}

const COLUMNS: Column<Row>[] = [
  { key: 'topic', header: 'Topic', mono: true, render: (row) => row.topic },
  {
    key: 'kind',
    header: '',
    render: (row) =>
      row.sparkplug ? (
        <StatusPill
          label="Sparkplug"
          tone="neutral"
          title="A Sparkplug topic is not part of the ISA-95 Asset Model, so it is expected here"
        />
      ) : null,
  },
];

/**
 * The Unmodelled Topics worklist.
 *
 * `total` comes from getAssetModelSummary, which counts every unbound topic, while this list
 * is capped by the query's limit. Showing a capped list beside an uncapped count without
 * saying so would understate the work.
 */
export const UnmodelledTopicsList: React.FC<{ total: number | null }> = ({ total }) => {
  const [topics, setTopics] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient
      .getUnmodelledTopics(LIMIT)
      .then((loaded) => {
        if (!cancelled) setTopics(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo<Row[]>(() => {
    const needle = filter.trim().toLowerCase();
    return (topics ?? [])
      .filter((topic) => needle === '' || topic.toLowerCase().includes(needle))
      .map((topic) => ({ topic, sparkplug: topic.startsWith(SPARKPLUG_PREFIX) }));
  }, [topics, filter]);

  if (error) return <EmptyState title="Could not read the Unmodelled Topics" detail={error} />;
  if (topics === null) {
    return <p className="px-4 py-3 text-[12px] text-[#64748B]">Reading Unmodelled Topics…</p>;
  }
  if (topics.length === 0) {
    return (
      <EmptyState
        title="Every published topic matches an Asset"
        detail="The Asset Model covers everything the broker has carried, so Enrichment applies to every historised measurement."
      />
    );
  }

  const truncated = total !== null && total > topics.length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-[#E2E8F0] px-3 py-1.5 dark:border-[#1E293B]">
        <label htmlFor="unmodelled-filter" className="text-[11px] text-[#64748B]">
          Filter
        </label>
        <input
          id="unmodelled-filter"
          value={filter}
          onChange={(changeEvent) => setFilter(changeEvent.target.value)}
          className="w-64 rounded border border-[#CBD5E1] bg-transparent px-2 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
        />
        <span className="text-[11px] text-[#64748B]">
          {rows.length} of {topics.length} shown
        </span>
        {truncated && (
          <span data-testid="unmodelled-truncated" className="text-[11px] text-amber-700 dark:text-amber-300">
            Loaded {topics.length} of {total}. The query returns at most {LIMIT}.
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1">
        <DataTable
          columns={COLUMNS}
          rows={rows}
          rowKey={(row) => row.topic}
          empty={
            <EmptyState
              title="No Unmodelled Topic matches this filter"
              detail="Clear the filter to see the whole worklist."
            />
          }
        />
      </div>

      <p className="shrink-0 border-t border-[#E2E8F0] px-3 py-1.5 text-[11px] text-[#64748B] dark:border-[#1E293B]">
        Assets are authored in the <span className="font-mono">simulator</span> section of{' '}
        <span className="font-mono">conf/settings.yaml</span> and applied by{' '}
        <span className="font-mono">docker compose up asset_model_setup</span>. A Sparkplug topic
        is expected to be unmodelled — the ISA-95 model does not describe it.
      </p>
    </div>
  );
};
```

- [ ] **Step 7: Write the failing view test**

Create `11_frontend/src/components/assets/AssetsView.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAssetModelSummary = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getAssetModelSummary: () => getAssetModelSummary() },
}));

vi.mock('./UnmodelledTopicsList', () => ({
  UnmodelledTopicsList: ({ total }: { total: number | null }) => <div>worklist of {String(total)}</div>,
}));

vi.mock('../plant/AssetTreeRail', () => ({
  AssetTreeRail: ({ onSelect }: { onSelect: (asset: unknown) => void }) => (
    <button type="button" onClick={() => onSelect({ path: 'CovestroAG/Dormagen', segment: 'Dormagen', level: 'SITE', name: 'Dormagen', isActive: true })}>
      pick Dormagen
    </button>
  ),
}));

vi.mock('../plant/tabs/ModelTab', () => ({
  ModelTab: ({ asset }: { asset: { path: string } }) => <div>model of {asset.path}</div>,
}));

import { AssetsView } from './AssetsView';

const SUMMARY = { assets: 42, metricDefinitions: 118, boundTopics: 610, unmodelledTopics: 7 };

describe('AssetsView', () => {
  beforeEach(() => {
    getAssetModelSummary.mockReset().mockResolvedValue(SUMMARY);
  });

  it('asks what to select before showing an Asset', async () => {
    render(<AssetsView />);
    expect(await screen.findByText(/select an asset/i)).toBeInTheDocument();
  });

  it('shows the selected Asset’s authored detail', async () => {
    render(<AssetsView />);
    await userEvent.click(await screen.findByRole('button', { name: /pick dormagen/i }));
    expect(screen.getByText('model of CovestroAG/Dormagen')).toBeInTheDocument();
  });

  it('opens the worklist from the Unmodelled count and passes it the total', async () => {
    render(<AssetsView />);
    await userEvent.click(await screen.findByRole('button', { name: /unmodelled/i }));
    expect(screen.getByText('worklist of 7')).toBeInTheDocument();
  });

  it('returns to the Asset detail when the count is clicked again', async () => {
    render(<AssetsView />);
    await userEvent.click(await screen.findByRole('button', { name: /pick dormagen/i }));
    await userEvent.click(screen.getByRole('button', { name: /unmodelled/i }));
    await userEvent.click(screen.getByRole('button', { name: /unmodelled/i }));
    expect(screen.getByText('model of CovestroAG/Dormagen')).toBeInTheDocument();
  });

  it('passes a null total when the summary could not be read', async () => {
    getAssetModelSummary.mockResolvedValue(null);
    render(<AssetsView />);
    expect(await screen.findByText(/could not read the asset model summary/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/assets/AssetsView.test.tsx
```

Expected: FAIL — `Failed to resolve import "./AssetsView"`.

- [ ] **Step 9: Write `AssetsView`**

```tsx
import React, { useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { AssetModelSummary, GraphqlAssetNode } from '../../services/graphql/types';
import { AssetTreeRail } from '../plant/AssetTreeRail';
import { ModelTab } from '../plant/tabs/ModelTab';
import { EmptyState } from '../common/EmptyState';
import { ModelSummaryHeader } from './ModelSummaryHeader';
import { UnmodelledTopicsList } from './UnmodelledTopicsList';

/**
 * The Asset Model as authored, and what it does not cover.
 *
 * The tree rail and the Asset detail are the PLANT components, not copies: this destination
 * asks a different question of the same authored model, and two implementations of "an
 * unauthored field renders as an em dash" is one too many.
 */
export const AssetsView: React.FC = () => {
  const [summary, setSummary] = useState<AssetModelSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GraphqlAssetNode | null>(null);
  const [showingUnmodelled, setShowingUnmodelled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient
      .getAssetModelSummary()
      .then((loaded) => {
        if (cancelled) return;
        // The client returns null for a failed read, so absence has to be reported as such.
        if (loaded === null) {
          setSummaryError('the query returned no summary');
          return;
        }
        setSummary(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setSummaryError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="assets-view">
      <ModelSummaryHeader
        summary={summary}
        error={summaryError}
        showingUnmodelled={showingUnmodelled}
        onShowUnmodelled={() => setShowingUnmodelled((showing) => !showing)}
      />

      <div className="flex min-h-0 flex-1">
        <div className="w-[320px] shrink-0 overflow-y-auto border-r border-[#E2E8F0] dark:border-[#1E293B]">
          <AssetTreeRail
            selectedPath={selected?.path ?? null}
            onSelect={(asset) => {
              setSelected(asset);
              setShowingUnmodelled(false);
            }}
          />
        </div>
        <div className="min-w-0 flex-1">
          {showingUnmodelled ? (
            <UnmodelledTopicsList total={summary?.unmodelledTopics ?? null} />
          ) : selected ? (
            <ModelTab asset={selected} />
          ) : (
            <EmptyState
              title="Select an Asset to see what is authored about it"
              detail="Or open the Unmodelled Topics count above to see the topics the model does not cover yet."
            />
          )}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 10: Point the route at it**

In `11_frontend/src/App.tsx`, replace the Task 1 placeholder for `/assets` with `<AssetsView />`. Add `getAssetModelSummary: vi.fn().mockResolvedValue(null)`, `getUnmodelledTopics: vi.fn().mockResolvedValue([])` and `getAssets: vi.fn().mockResolvedValue([])` to the client mock in `App.routes.test.tsx` if they are not already there.

- [ ] **Step 11: Run everything**

```bash
cd 11_frontend && npx vitest run src/components/assets src/App.routes.test.tsx && npx tsc --noEmit && npm run lint
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add 11_frontend/src/components/assets/ 11_frontend/src/App.tsx 11_frontend/src/App.routes.test.tsx
git commit -m "feat(frontend): make the Asset Model and its gaps reachable

getAssetModelSummary and getUnmodelledTopics existed in the schema and nothing called
them, so an integration engineer had no way to see which published topics the model does
not cover. The completeness header is the way in, and clicking the Unmodelled count opens
the worklist - the path spec section 16 describes.

Three honesty details. A failed summary read renders as a failed read, not as four zeros
claiming the plant has no Asset Model. The worklist says when it is capped at the query's
limit of 100 against a larger count. Sparkplug topics are marked as expected here, and
the footer names conf/settings.yaml and asset_model_setup as where an Asset is authored.

The tree rail and the Asset detail are the PLANT components reused, not copies."
```

---

## Task 17: NAMESPACE — what the broker is actually carrying

Spec tests 9 and 10 both live here. This is the integration engineer's destination: the graph of UNS Nodes discovered from traffic, as distinct from the authored Asset Model at `/assets` (spec section 7 — "a machine which has not published yet simply did not exist" in the former, and merging them is how a missing Asset becomes invisible).

Four facts from the repo, two of which are defects this task removes:

1. **The tree already obeys the wildcard rules.** `client.ts:207` resolves roots through `getAssetChildren(null)` then `childrenTopic('')`; `:223` resolves children through the Asset Model then `childrenTopic(parentTopic)`. `childrenTopic` (`lib/uns/topics.ts:6`) returns `+` or `{topic}/+`. No tree path builds a `#`. Nothing to fix; there is something to *prove*, which is spec test 9.
2. **The tree invents children.** `client.ts:231-246` falls back to `syntheticSensorNodes` and `syntheticParameterGroupNodes` (`lib/uns/isa95-probe.ts`), which return rows named `ProcessValue`, `Setpoint`, `Status`, `Alarm`, `EVENT`, `Temperature`, `Pressure`, `FlowRate`, `Level`, `Humidity` and `EquipmentStatus` under *any* topic deep enough — whether or not the plant publishes them. `lib/uns/map-assets.ts:9-11` already says why that is wrong: "The segments below a machine used to come from a hardcoded list of names the simulator happened to publish, which was wrong for every plant that is not the simulator", and `metricChildNodes` is its replacement. This task finishes that migration by deleting the probe. The honest answer when the Asset Model declares nothing and a `+` query returns nothing is that nothing has been published there.
3. **The search box filters the tree.** `UnsTreeView.tsx:59-64` returns `null` for any node whose topic does not contain the query and whose loaded children do not either. So typing hides plant structure, which is exactly the behaviour the constraints forbid: matches are a list, and clicking one expands ancestors. `UNSContext.jumpToTopicInTree` (`:299-322`) already does that expansion, so the list needs no new machinery.
4. **`getUnsNodesByProperty` is a real server-side search, and it is not a topic search.** Its description is "Get all UNSNodes published which have specific attribute name as 'propertyKeys'" — it matches *payload keys*, optionally filtered by topic wildcards, with `excludeTopics` inverting the filter (`queries/graph.py:312-347`). It takes no `AND`/`OR`/`NOT` operator; only `getHistoricEventsByProperty` does. So the panel offers no operator control, because a control that cannot change the result is another untruth. Per the gap table it moves out of the historian, where it is currently the fourth mode of a form otherwise about Historic Events (`ExploreView.tsx:114`). This task adds it to NAMESPACE; Task 18 removes the mode from the historian form. For one commit the query is reachable from two screens, which is better than a broken build in between.

There is no server-side topic-substring search. The tree's text search therefore matches the nodes already loaded in this browser and says so; a server-side topic search is marked **requires backend**.

`components/home/` keeps its three leaf components, per this plan's file table: `NamespaceView` is a shell around them, not a rewrite. The directory name no longer matches a destination, and renaming it is deliberately not done here — it would be a large diff with no behaviour change, and every import in it is about to be read by a reviewer for the changes that matter.

**Files:**
- Create: `11_frontend/src/lib/uns/tree-search.ts`
- Test: `11_frontend/src/lib/uns/tree-search.test.ts`
- Delete: `11_frontend/src/lib/uns/isa95-probe.ts`
- Modify: `11_frontend/src/services/graphql/client.ts:223-249`
- Test: `11_frontend/src/services/graphql/client-tree.test.ts`
- Modify: `11_frontend/src/lib/uns/node-meta.ts:34-46` (comments only)
- Modify: `11_frontend/src/context/UNSContext.tsx:299-322`
- Modify: `11_frontend/src/components/home/UnsTreeView.tsx`
- Test: `11_frontend/src/components/home/UnsTreeView.test.tsx`
- Create: `11_frontend/src/components/namespace/FindByProperty.tsx`
- Test: `11_frontend/src/components/namespace/FindByProperty.test.tsx`
- Create: `11_frontend/src/components/namespace/NamespaceView.tsx`
- Test: `11_frontend/src/components/namespace/NamespaceView.test.tsx`
- Modify: `11_frontend/src/App.tsx`

**Interfaces:**
- Consumes: `unsGraphQLClient.getUnsNodesByProperty(propertyKeys, topics?, excludeTopics?)` (already in the repo at `client.ts:363`), `useUNS()`, `UnsTreeView`, `PayloadInspector`, `LiveMqttFeed`, `EmptyState`, `StatusPill`, `isSparkplugTopic` (`lib/uns/sparkplug.ts`).
- Produces:
  ```ts
  // src/lib/uns/tree-search.ts
  /** Every ancestor of a topic, shallowest first, excluding the topic itself. */
  export function ancestorTopics(topic: string): string[];
  /** Case-insensitive substring match on topic and name, capped, ordered by topic. */
  export function matchLoadedNodes(nodes: UnsNode[], query: string, limit?: number): UnsNode[];
  export const MATCH_LIMIT = 50;
  ```
  ```tsx
  export const FindByProperty: React.FC;
  export const NamespaceView: React.FC;
  ```
  Nothing later in this plan consumes these.

- [ ] **Step 1: Write the failing search-helper test**

Create `11_frontend/src/lib/uns/tree-search.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { UnsNode } from '../../types/uns'
import { ancestorTopics, matchLoadedNodes, MATCH_LIMIT } from './tree-search'

const node = (topic: string, name = topic.split('/').pop() ?? topic): UnsNode => ({
  topic,
  name,
  namespace: topic,
  lastUpdated: new Date(0).toISOString(),
  isLeaf: false,
})

describe('ancestorTopics', () => {
  it('lists every ancestor shallowest first and excludes the topic itself', () => {
    expect(ancestorTopics('CovestroAG/Dormagen/Production/Line1')).toEqual([
      'CovestroAG',
      'CovestroAG/Dormagen',
      'CovestroAG/Dormagen/Production',
    ])
  })

  it('has no ancestors for a root', () => {
    expect(ancestorTopics('CovestroAG')).toEqual([])
  })

  it('ignores empty segments rather than producing a blank ancestor', () => {
    expect(ancestorTopics('a//b')).toEqual(['a'])
  })
})

describe('matchLoadedNodes', () => {
  const loaded = [
    node('CovestroAG/Dormagen/Production/Line1'),
    node('CovestroAG/Dormagen/Utilities/Chiller_02'),
    node('CovestroAG/Krefeld/Production/Line1'),
  ]

  it('matches on the topic, case-insensitively', () => {
    expect(matchLoadedNodes(loaded, 'chiller').map((n) => n.topic)).toEqual([
      'CovestroAG/Dormagen/Utilities/Chiller_02',
    ])
  })

  it('matches on the authored name, which is what the row shows', () => {
    const named = [node('CovestroAG/Dormagen/Production/Line1/G1', 'Filler 3')]
    expect(matchLoadedNodes(named, 'filler').map((n) => n.topic)).toEqual([
      'CovestroAG/Dormagen/Production/Line1/G1',
    ])
  })

  it('orders by topic so the same query always lists the same way', () => {
    expect(matchLoadedNodes(loaded, 'line1').map((n) => n.topic)).toEqual([
      'CovestroAG/Dormagen/Production/Line1',
      'CovestroAG/Krefeld/Production/Line1',
    ])
  })

  it('returns nothing for a blank query rather than everything', () => {
    expect(matchLoadedNodes(loaded, '   ')).toEqual([])
  })

  it('caps the list so a one-letter query cannot render the whole graph', () => {
    const many = Array.from({ length: MATCH_LIMIT + 10 }, (_, i) =>
      node(`Plant/Line${String(i).padStart(3, '0')}`),
    )
    expect(matchLoadedNodes(many, 'line')).toHaveLength(MATCH_LIMIT)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/uns/tree-search.test.ts
```

Expected: FAIL — `Failed to resolve import "./tree-search"`.

- [ ] **Step 3: Write `tree-search.ts`**

```ts
/**
 * Finding a topic in the tree without hiding the tree.
 *
 * The graph database has no substring search over topics — getUnsNodes takes exact
 * topics and MQTT wildcards — so a text query is answered from the nodes this browser
 * has already loaded. Every caller must say so; a search that silently covers part of
 * the namespace and looks like it covers all of it is worse than no search.
 * **requires backend** for a server-side topic search.
 */

import type { UnsNode } from '../../types/uns'

/** More rows than this is a list nobody reads, and a query that needs narrowing. */
export const MATCH_LIMIT = 50

/** Every ancestor of a topic, shallowest first, excluding the topic itself. */
export function ancestorTopics(topic: string): string[] {
  const segments = topic.split('/').filter(Boolean)
  const ancestors: string[] = []
  for (let i = 0; i < segments.length - 1; i += 1) {
    ancestors.push(segments.slice(0, i + 1).join('/'))
  }
  return ancestors
}

export function matchLoadedNodes(
  nodes: UnsNode[],
  query: string,
  limit: number = MATCH_LIMIT,
): UnsNode[] {
  const needle = query.trim().toLowerCase()
  if (needle === '') return []
  return nodes
    .filter(
      (node) =>
        node.topic.toLowerCase().includes(needle) || node.name.toLowerCase().includes(needle),
    )
    .sort((a, b) => a.topic.localeCompare(b.topic))
    .slice(0, limit)
}
```

- [ ] **Step 4: Write the failing tree-client test**

This is spec test 9. Create `11_frontend/src/services/graphql/client-tree.test.ts`. The harness is the one foundation Task 8 established in `client-assets.test.ts` — copy `silentSocket`, `respond` and `sentBody` from that file rather than inventing a second shape.

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'

function silentSocket() {
  vi.stubGlobal(
    'WebSocket',
    class {
      onopen = null
      onmessage = null
      onerror = null
      onclose = null
      send() {}
      close() {}
    },
  )
}

/** Replies to every call in order; a shorter list than the calls made is a test bug. */
function respondInOrder(...payloads: unknown[]) {
  const fetchMock = vi.fn()
  for (const data of payloads) {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ data }) })
  }
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodies(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.map((call) => JSON.parse(call[1].body as string))
}

const graphNode = (topic: string, nodeType = 'DEVICE_depth_1') => ({
  nodeName: topic.split('/').pop(),
  nodeType,
  namespace: topic,
  payload: { data: '{"value": 1}' },
  created: '2026-09-01T00:00:00Z',
  lastUpdated: '2026-09-02T06:00:00Z',
})

describe('the ISA-95 tree', () => {
  let client: UnsGraphQLClient

  beforeEach(() => {
    silentSocket()
    client = new UnsGraphQLClient('/graphql')
  })

  // Spec test 9, first half.
  it('expands one level at a time and never sends a multi-level wildcard', async () => {
    const fetchMock = respondInOrder(
      { getAssetChildren: [], getTopicContext: null },
      { getUnsNodes: [graphNode('CovestroAG/Dormagen/Utilities/Chiller_02')] },
    )

    await client.getUnsNodeChildren('CovestroAG/Dormagen/Utilities')

    const sent = JSON.stringify(bodies(fetchMock))
    expect(sent).toContain('CovestroAG/Dormagen/Utilities/+')
    expect(sent).not.toContain('#')
  })

  it('asks for roots with a bare + when the Asset Model is empty', async () => {
    const fetchMock = respondInOrder(
      { getAssetChildren: [] },
      { getUnsNodes: [graphNode('CovestroAG', 'ENTERPRISE')] },
    )

    await client.getUnsRootNodes()

    const sent = JSON.stringify(bodies(fetchMock))
    expect(sent).toContain('"topic":"+"')
    expect(sent).not.toContain('#')
  })

  // Spec test 9, second half.
  it('keeps Sparkplug out of the ISA-95 tree', async () => {
    const fetchMock = respondInOrder(
      { getAssetChildren: [] },
      { getUnsNodes: [graphNode('CovestroAG', 'ENTERPRISE'), graphNode('spBv1.0', 'ENTERPRISE')] },
    )

    const roots = await client.getUnsRootNodes()

    expect(roots.map((node) => node.topic)).toEqual(['CovestroAG'])
    expect(bodies(fetchMock)).toHaveLength(2)
  })

  it('keeps Sparkplug out of a node’s children too', async () => {
    respondInOrder(
      { getAssetChildren: [], getTopicContext: null },
      { getUnsNodes: [graphNode('spBv1.0/CovestroAG'), graphNode('CovestroAG/Dormagen')] },
    )

    const children = await client.getUnsNodeChildren('CovestroAG')

    expect(children.map((node) => node.topic)).toEqual(['CovestroAG/Dormagen'])
  })

  // The probe deletion.
  it('reports an empty branch as empty instead of inventing sensor names', async () => {
    respondInOrder(
      { getAssetChildren: [], getTopicContext: null },
      { getUnsNodes: [] },
    )

    const children = await client.getUnsNodeChildren(
      'CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue',
    )

    expect(children).toEqual([])
  })

  it('does not invent parameter groups below a machine', async () => {
    respondInOrder(
      { getAssetChildren: [], getTopicContext: null },
      { getUnsNodes: [] },
    )

    const children = await client.getUnsNodeChildren(
      'CovestroAG/Dormagen/Production/Line1/Cell1/G1',
    )

    expect(children.map((node) => node.name)).toEqual([])
  })
})
```

Confirm the `graphNode` field names against `graphqlUnsNodeToUnsNode` in `src/services/graphql/mappers.ts` (or wherever `client.ts:5-30` imports it from) before running. If the mapper reads `node_name` rather than `nodeName`, the mapper wins and this fixture is wrong.

- [ ] **Step 5: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/services/graphql/client-tree.test.ts
```

Expected: FAIL on the Sparkplug tests and the two empty-branch tests. The wildcard tests should already pass — fact 1 says the behaviour is correct today, and these two tests exist to keep it that way.

- [ ] **Step 6: Delete the probe and filter Sparkplug out of the tree**

Delete `11_frontend/src/lib/uns/isa95-probe.ts`.

In `client.ts`, drop the `isParameterGroupTopic`, `syntheticSensorNodes`, `syntheticParameterGroupNodes` and `topicDepth` imports (check whether `topicDepth` is used anywhere else in the file first; if it is, keep it), and replace `getUnsRootNodes` and `getUnsNodeChildren`:

```ts
  /**
   * The roots of the tree: the Asset Model's, or the graph database's when nothing has
   * been modelled yet.
   *
   * An empty Asset Model is a platform that has been deployed but not yet described,
   * and it must still show the traffic it is receiving.
   */
  public async getUnsRootNodes(): Promise<UnsNode[]> {
    const roots = await this.getAssetChildren(null)
    if (roots.length > 0) {
      return roots.map(assetToUnsNode)
    }
    return withoutSparkplug(await this.getUnsNodes([childrenTopic('')]))
  }

  /**
   * Children of a node: what the Asset Model declares below it, and what has been
   * published below it where the model does not reach.
   *
   * Nothing is guessed. A branch with no authored Metric Definitions and no published
   * traffic is empty, and the tree says so by not expanding. The hardcoded segment
   * names that used to fill that gap named sensors the simulator happens to publish
   * (see lib/uns/map-assets.ts) and were wrong for every other plant.
   */
  public async getUnsNodeChildren(parentTopic: string): Promise<UnsNode[]> {
    const modelled = await this.getModelledChildren(parentTopic)
    if (modelled.length > 0) {
      return modelled
    }
    return withoutSparkplug(await this.getUnsNodes([childrenTopic(parentTopic)]))
  }
```

Add the filter as a module-level function near the top of `client.ts`, beside the other helpers:

```ts
/**
 * Sparkplug has its own destination and its own decoder. `spBv1.0/` is not part of the
 * ISA-95 hierarchy, and `DEVICE` is a label in both the UNS and the Sparkplug node-type
 * sets (`07_uns_graphql/src/uns_graphql/graphql_config.py:103-106`), so this is a cheap
 * guarantee rather than a redundant one.
 */
function withoutSparkplug(nodes: UnsNode[]): UnsNode[] {
  return nodes.filter((node) => !isSparkplugTopic(node.topic))
}
```

importing `isSparkplugTopic` from `../../lib/uns/sparkplug`.

Then fix the two comments in `lib/uns/node-meta.ts` that refer to the deleted probe — `hasNoTelemetryClock`'s "or a placeholder the tree probed for" and `isSyntheticUnsNode`'s "Placeholder or authored nodes". Both functions stay: `assetToUnsNode` and `metricChildNodes` still produce epoch-`lastUpdated` nodes (`lib/uns/map-assets.ts:31`), which is what `UNSContext.selectNode:137` uses them for.

```ts
/**
 * True when a node has never carried telemetry: an Asset or a Metric the Asset Model
 * declares but nothing has published to yet. Its payload has to be fetched before it
 * can be shown, and it must not be counted as a stale sensor in the meantime.
 */
export function hasNoTelemetryClock(node: Pick<UnsNode, 'lastUpdated'>): boolean {
  return new Date(node.lastUpdated).getTime() <= 0
}

/** Authored nodes that have no live payload in the graph database yet. */
export function isSyntheticUnsNode(node: Pick<UnsNode, 'lastUpdated'>): boolean {
  return hasNoTelemetryClock(node)
}
```

- [ ] **Step 7: Run the tree tests and the whole suite**

```bash
cd 11_frontend && npx vitest run src/services/graphql && npx tsc --noEmit
```

Expected: PASS. `tsc` catches any remaining import of the deleted module. If a component imported `ISA95_PARAMETER_GROUPS` or `probeSensorTopics` directly, remove that use rather than reinstating the file — `grep -rn "isa95-probe" src` must print nothing.

- [ ] **Step 8: Write the failing topic-browser test**

This is spec test 10. Create `11_frontend/src/components/home/UnsTreeView.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UnsNode } from '../../types/uns';

const node = (topic: string, children?: UnsNode[]): UnsNode => ({
  topic,
  name: topic.split('/').pop() ?? topic,
  namespace: topic,
  nodeType: children ? 'AREA' : 'DEVICE_depth_1',
  lastUpdated: '2026-09-02T06:00:00Z',
  isLeaf: !children,
  children,
});

const TREE = [
  node('CovestroAG', [
    node('CovestroAG/Dormagen', [
      node('CovestroAG/Dormagen/Production'),
      node('CovestroAG/Dormagen/Utilities'),
    ]),
  ]),
];

const LOADED = [
  TREE[0],
  TREE[0].children![0],
  ...TREE[0].children![0].children!,
  node('CovestroAG/Krefeld/Production/Line1/Cell1/Chiller_02'),
];

const jumpToTopicInTree = vi.fn();
const toggleNodeExpanded = vi.fn();

const harness = {
  rootNodes: TREE,
  expandedNodes: new Set(['CovestroAG', 'CovestroAG/Dormagen']),
  toggleNodeExpanded,
  selectedNode: null,
  selectNode: vi.fn(),
  treeLoading: false,
  refreshTree: vi.fn(),
  settings: { staleThresholdMinutes: 5 },
  isBookmarked: () => false,
  addBookmark: vi.fn(),
  removeBookmark: vi.fn(),
  allLoadedNodes: LOADED,
  jumpToTopicInTree,
};

vi.mock('../../context/UNSContext', () => ({ useUNS: () => harness }));

import { UnsTreeView } from './UnsTreeView';

const treeRows = () =>
  within(screen.getByTestId('tree-body'))
    .queryAllByRole('treeitem')
    .map((row) => row.getAttribute('data-topic'));

describe('UnsTreeView search', () => {
  beforeEach(() => {
    jumpToTopicInTree.mockReset();
    toggleNodeExpanded.mockReset();
  });

  // Spec test 10, first half.
  it('leaves the tree’s rows unchanged while searching', async () => {
    render(<UnsTreeView />);
    const before = treeRows();
    await userEvent.type(screen.getByLabelText(/find a topic/i), 'Chiller');
    expect(treeRows()).toEqual(before);
  });

  it('lists the matches separately from the tree', async () => {
    render(<UnsTreeView />);
    await userEvent.type(screen.getByLabelText(/find a topic/i), 'Chiller');
    const matches = screen.getByTestId('tree-matches');
    expect(within(matches).getByText(/Krefeld\/Production\/Line1\/Cell1\/Chiller_02/)).toBeInTheDocument();
    expect(within(matches).getByText(/1 match/i)).toBeInTheDocument();
  });

  // Spec test 10, second half.
  it('expands the ancestors of a match when it is clicked', async () => {
    render(<UnsTreeView />);
    await userEvent.type(screen.getByLabelText(/find a topic/i), 'Chiller');
    await userEvent.click(
      within(screen.getByTestId('tree-matches')).getByRole('button', { name: /Chiller_02/ }),
    );
    expect(jumpToTopicInTree).toHaveBeenCalledWith(
      'CovestroAG/Krefeld/Production/Line1/Cell1/Chiller_02',
    );
  });

  it('says what the search covers instead of implying it covers the broker', async () => {
    render(<UnsTreeView />);
    await userEvent.type(screen.getByLabelText(/find a topic/i), 'Chiller');
    expect(screen.getByTestId('tree-matches').textContent).toMatch(
      /5 topics loaded in this browser/i,
    );
  });

  it('says nothing matched, and why that is not the same as nothing existing', async () => {
    render(<UnsTreeView />);
    await userEvent.type(screen.getByLabelText(/find a topic/i), 'Reactor_01');
    const matches = screen.getByTestId('tree-matches');
    expect(within(matches).getByText(/no loaded topic matches/i)).toBeInTheDocument();
    expect(within(matches).getByText(/expand more of the tree/i)).toBeInTheDocument();
  });

  it('shows no match list at all until something is typed', () => {
    render(<UnsTreeView />);
    expect(screen.queryByTestId('tree-matches')).not.toBeInTheDocument();
  });

  it('states the wildcard rule the tree follows', () => {
    render(<UnsTreeView />);
    const banner = screen.getByTestId('tree-wildcard-note').textContent ?? '';
    expect(banner).toContain('+');
    expect(banner).toMatch(/one level at a time/i);
  });
});
```

The `settings` field in the harness only needs `staleThresholdMinutes` because that is all `UnsTreeView` reads from it. If it reads more, widen the harness rather than the component.

- [ ] **Step 9: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/home/UnsTreeView.test.tsx
```

Expected: FAIL. There is no `tree-body` test id, no `treeitem` role, no `tree-matches`, and the label is `Filter namespace topics...` as a placeholder rather than an accessible label.

- [ ] **Step 10: Rework the tree's search**

Four edits to `11_frontend/src/components/home/UnsTreeView.tsx`.

First, delete the filter block at `:59-64` entirely — the six lines from `// Filter by search query if present` to the closing brace. Nothing replaces it inside `renderNode`.

Second, give each row the tree semantics the test asserts, on the row `div` that already carries the `id`:

```tsx
          role="treeitem"
          data-topic={node.topic}
          aria-expanded={isExpandable ? isExpanded : undefined}
          aria-selected={isSelected}
```

Third, replace the search input with a labelled one and add the match list. Pull `allLoadedNodes` and `jumpToTopicInTree` from `useUNS()`, and compute:

```tsx
  const matches = useMemo(
    () => matchLoadedNodes(allLoadedNodes, searchQuery),
    [allLoadedNodes, searchQuery],
  );
  const searching = searchQuery.trim() !== '';
```

The input:

```tsx
        <div className="relative">
          <Search className="w-3 h-3 text-[#64748B] absolute left-2 top-2 pointer-events-none" />
          <label htmlFor="tree-search" className="sr-only">
            Find a topic
          </label>
          <input
            id="tree-search"
            type="text"
            placeholder="Find a topic"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-white dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded pl-7 pr-2 py-1 text-[11px] text-[#0F172A] dark:text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono"
          />
        </div>
```

The match list, rendered between the header and the tree body so it never displaces plant structure:

```tsx
      {searching && (
        <div
          data-testid="tree-matches"
          className="max-h-48 shrink-0 overflow-y-auto border-b border-[#E2E8F0] bg-[#F8FAFC] dark:border-[#1E293B] dark:bg-[#111114]"
        >
          <div className="flex items-baseline justify-between px-2.5 py-1 text-[11px] text-[#64748B]">
            <span>
              {matches.length === MATCH_LIMIT ? `First ${MATCH_LIMIT} matches` : `${matches.length} match${matches.length === 1 ? '' : 'es'}`}
            </span>
            <span>of {allLoadedNodes.length} topics loaded in this browser</span>
          </div>

          {matches.length === 0 ? (
            <p className="px-2.5 pb-2 text-[11px] text-[#64748B]">
              No loaded topic matches. Expand more of the tree to search deeper — the graph
              database has no topic search, so this only covers what has been loaded.
            </p>
          ) : (
            <ul>
              {matches.map((match) => (
                <li key={match.topic}>
                  <button
                    type="button"
                    onClick={() => void jumpToTopicInTree(match.topic)}
                    className="block w-full truncate px-2.5 py-0.5 text-left font-mono text-[11px] text-[#0F172A] hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:text-[#E2E8F0] dark:hover:bg-[#1E293B]/60"
                    title={match.topic}
                  >
                    {match.topic}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
```

Fourth, replace the query banner at the component's `Query: getUnsNodes(["+"])` block. It is wrong whenever the Asset Model is populated, because roots then come from `getAssetChildren(null)`. State the rule instead of the call:

```tsx
      <div
        data-testid="tree-wildcard-note"
        className="flex items-center justify-between border-b border-[#E2E8F0] bg-slate-100 px-2.5 py-1 font-mono text-[11px] text-[#64748B] dark:border-[#1E293B] dark:bg-[#111114]/70"
      >
        <span>Expanded one level at a time (+)</span>
        <span>Never #</span>
      </div>
```

And put `role="tree"` and `data-testid="tree-body"` on the scrolling tree container, so the `treeitem` rows sit inside the role that owns them.

- [ ] **Step 11: Use `ancestorTopics` where the ancestors are expanded**

In `11_frontend/src/context/UNSContext.tsx`, replace the hand-rolled segment loop inside `jumpToTopicInTree` with the tested helper. The behaviour is identical; the point is that the "expands ancestors" half of spec test 10 now rests on something with unit tests.

```ts
  const jumpToTopicInTree = async (targetTopic: string) => {
    setActiveTab('namespace');
    if (window.location.hash !== '#/namespace') {
      window.location.hash = '#/namespace';
    }

    const expanded = new Set(expandedNodes);
    for (const ancestor of ancestorTopics(targetTopic)) {
      expanded.add(ancestor);
      const children = await unsGraphQLClient.getUnsNodeChildren(ancestor);
      setNodeChildrenMap((prev) => new Map(prev).set(ancestor, children));
    }
    setExpandedNodes(expanded);

    const nodes = await unsGraphQLClient.getUnsNodes([targetTopic]);
    if (nodes.length > 0) {
      setSelectedNode(nodes[0]);
    }
  };
```

Import `ancestorTopics` from `../lib/uns/tree-search`.

- [ ] **Step 12: Run the browser tests**

```bash
cd 11_frontend && npx vitest run src/components/home/UnsTreeView.test.tsx src/lib/uns
```

Expected: PASS.

- [ ] **Step 13: Write the failing property-search test**

Create `11_frontend/src/components/namespace/FindByProperty.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getUnsNodesByProperty = vi.fn();
const jumpToTopicInTree = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getUnsNodesByProperty: (...args: unknown[]) => getUnsNodesByProperty(...args),
  },
}));
vi.mock('../../context/UNSContext', () => ({ useUNS: () => ({ jumpToTopicInTree }) }));

import { FindByProperty } from './FindByProperty';

const MATCH = {
  topic: 'CovestroAG/Dormagen/Utilities/Chiller_02/temperature',
  name: 'temperature',
  namespace: 'CovestroAG/Dormagen/Utilities/Chiller_02/temperature',
  lastUpdated: '2026-09-02T06:00:00Z',
  isLeaf: true,
};

describe('FindByProperty', () => {
  beforeEach(() => {
    getUnsNodesByProperty.mockReset().mockResolvedValue([MATCH]);
    jumpToTopicInTree.mockReset();
  });

  it('sends the payload keys it was given, splitting on commas', async () => {
    render(<FindByProperty />);
    await userEvent.clear(screen.getByLabelText(/payload key/i));
    await userEvent.type(screen.getByLabelText(/payload key/i), 'temperature, setpoint');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    expect(getUnsNodesByProperty).toHaveBeenCalledWith(
      ['temperature', 'setpoint'],
      ['spBv1.0/#'],
      true,
    );
  });

  it('excludes Sparkplug by default and says where it is read instead', () => {
    render(<FindByProperty />);
    expect((screen.getByLabelText(/exclude topics/i) as HTMLInputElement).value).toBe('spBv1.0/#');
    expect(screen.getByText(/decoded on the Sparkplug screen/i)).toBeInTheDocument();
  });

  it('sends no topic filter when the exclude box is cleared', async () => {
    render(<FindByProperty />);
    await userEvent.clear(screen.getByLabelText(/exclude topics/i));
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    expect(getUnsNodesByProperty).toHaveBeenCalledWith(['temperature'], undefined, false);
  });

  it('lists each matching topic and can show it in the tree', async () => {
    render(<FindByProperty />);
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    const row = (await screen.findByText(MATCH.topic)).closest('li')!;
    await userEvent.click(within(row).getByRole('button', { name: /show in tree/i }));
    expect(jumpToTopicInTree).toHaveBeenCalledWith(MATCH.topic);
  });

  it('offers no operator, because the query has none', () => {
    render(<FindByProperty />);
    expect(screen.queryByLabelText(/operator/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'AND' })).not.toBeInTheDocument();
  });

  it('distinguishes no results from not having searched', async () => {
    getUnsNodesByProperty.mockResolvedValue([]);
    render(<FindByProperty />);
    expect(screen.getByText(/enter a payload key/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    expect(await screen.findByText(/no UNS Node carries/i)).toBeInTheDocument();
  });

  it('will not search with no key', async () => {
    render(<FindByProperty />);
    await userEvent.clear(screen.getByLabelText(/payload key/i));
    expect(screen.getByRole('button', { name: /^search$/i })).toBeDisabled();
    expect(getUnsNodesByProperty).not.toHaveBeenCalled();
  });

  it('shows a failed search rather than an empty list', async () => {
    getUnsNodesByProperty.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    render(<FindByProperty />);
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    expect(await screen.findByText(/GraphQL endpoint unreachable/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 14: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/namespace/FindByProperty.test.tsx
```

Expected: FAIL — `Failed to resolve import "./FindByProperty"`.

- [ ] **Step 15: Write `FindByProperty`**

```tsx
import React, { useState } from 'react';
import type { UnsNode } from '../../types/uns';
import { unsGraphQLClient } from '../../services/graphql/client';
import { useUNS } from '../../context/UNSContext';
import { isSparkplugTopic, SPARKPLUG_PREFIX } from '../../lib/uns/sparkplug';
import { StatusPill } from '../common/StatusPill';

/** The Sparkplug namespace, as an MQTT filter the server turns into a regex. */
const SPARKPLUG_FILTER = `${SPARKPLUG_PREFIX}#`;

const splitList = (raw: string): string[] =>
  raw
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);

/**
 * Which topics carry a given payload key.
 *
 * This is getUnsNodesByProperty, whose own description is "Get all UNSNodes published
 * which have specific attribute name as 'propertyKeys'" — it matches keys inside the
 * payload, not topic segments, and it takes no AND/OR/NOT operator. The `#` in the
 * exclude box is legitimate: it is a topic filter the server compiles to a regex, not
 * a tree expansion.
 */
export const FindByProperty: React.FC = () => {
  const { jumpToTopicInTree } = useUNS();
  const [keysInput, setKeysInput] = useState('temperature');
  const [excludeInput, setExcludeInput] = useState(SPARKPLUG_FILTER);
  const [results, setResults] = useState<UnsNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const keys = splitList(keysInput);

  const search = async () => {
    const excludes = splitList(excludeInput);
    setRunning(true);
    setError(null);
    try {
      const found = await unsGraphQLClient.getUnsNodesByProperty(
        keys,
        excludes.length ? excludes : undefined,
        excludes.length > 0,
      );
      setResults(found);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setResults(null);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2 border-b border-[#E2E8F0] px-3 py-2 dark:border-[#1E293B]">
        <h2 className="text-[12px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">
          Find by payload key
        </h2>

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-0.5">
            <label htmlFor="prop-keys" className="block text-[11px] text-[#64748B]">
              Payload keys, comma separated
            </label>
            <input
              id="prop-keys"
              value={keysInput}
              onChange={(changeEvent) => setKeysInput(changeEvent.target.value)}
              className="w-64 rounded border border-[#CBD5E1] bg-transparent px-2 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
            />
          </div>

          <div className="space-y-0.5">
            <label htmlFor="prop-exclude" className="block text-[11px] text-[#64748B]">
              Exclude topics
            </label>
            <input
              id="prop-exclude"
              value={excludeInput}
              onChange={(changeEvent) => setExcludeInput(changeEvent.target.value)}
              className="w-56 rounded border border-[#CBD5E1] bg-transparent px-2 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-[#334155]"
            />
          </div>

          <button
            type="button"
            onClick={() => void search()}
            disabled={keys.length === 0 || running}
            className="rounded bg-sky-600 px-3 py-1 text-[11px] font-medium text-white disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-sky-400"
          >
            Search
          </button>
        </div>

        <p className="text-[11px] text-[#64748B]">
          Matches keys inside the published payload, not topic segments. Sparkplug topics are
          excluded by default — they are decoded on the Sparkplug screen, never here.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {error && <p className="px-3 py-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}

        {!error && results === null && (
          <p className="px-3 py-2 text-[12px] text-[#64748B]">
            Enter a payload key and search. Every UNS Node whose payload carries that key is
            listed with its topic.
          </p>
        )}

        {!error && results !== null && results.length === 0 && (
          <p className="px-3 py-2 text-[12px] text-[#64748B]">
            No UNS Node carries {keys.map((key) => `"${key}"`).join(' or ')}. Nothing has
            published that key, or the exclude filter removed it.
          </p>
        )}

        {!error && results !== null && results.length > 0 && (
          <ul className="divide-y divide-[#E2E8F0] dark:divide-[#1E293B]">
            {results.map((node) => (
              <li
                key={node.topic}
                className="flex items-center justify-between gap-2 px-3 py-1 text-[11px]"
              >
                <span className="truncate font-mono text-[#0F172A] dark:text-[#E2E8F0]">
                  {node.topic}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {isSparkplugTopic(node.topic) && (
                    <StatusPill
                      label="Sparkplug"
                      tone="neutral"
                      title="Read this on the Sparkplug screen; the console does not decode it here"
                    />
                  )}
                  <button
                    type="button"
                    onClick={() => void jumpToTopicInTree(node.topic)}
                    className="rounded px-1.5 py-0.5 text-[11px] text-sky-700 hover:bg-sky-500/10 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:text-sky-300"
                  >
                    Show in tree
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};
```

`StatusPill`'s prop names come from Task 5 — use whatever it actually exports rather than this call shape if they differ.

- [ ] **Step 16: Write the failing view test**

Create `11_frontend/src/components/namespace/NamespaceView.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../home/UnsTreeView', () => ({ UnsTreeView: () => <div>topic tree</div> }));
vi.mock('../home/PayloadInspector', () => ({ PayloadInspector: () => <div>payload</div> }));
vi.mock('../home/LiveMqttFeed', () => ({ LiveMqttFeed: () => <div>live feed</div> }));
vi.mock('./FindByProperty', () => ({ FindByProperty: () => <div>property search</div> }));

import { NamespaceView } from './NamespaceView';

describe('NamespaceView', () => {
  it('shows the tree, the payload and the feed together', () => {
    render(<NamespaceView />);
    expect(screen.getByText('topic tree')).toBeInTheDocument();
    expect(screen.getByText('payload')).toBeInTheDocument();
    expect(screen.getByText('live feed')).toBeInTheDocument();
  });

  it('says what this destination shows, and what it does not', () => {
    render(<NamespaceView />);
    expect(screen.getByText(/discovered from published traffic/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /assets/i })).toHaveAttribute('href', '#/assets');
  });

  it('swaps the payload pane for the property search on request', async () => {
    render(<NamespaceView />);
    await userEvent.click(screen.getByRole('button', { name: /find by payload key/i }));
    expect(screen.getByText('property search')).toBeInTheDocument();
    expect(screen.queryByText('payload')).not.toBeInTheDocument();
    expect(screen.getByText('topic tree')).toBeInTheDocument();
  });
});
```

- [ ] **Step 17: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/namespace/NamespaceView.test.tsx
```

Expected: FAIL — `Failed to resolve import "./NamespaceView"`.

- [ ] **Step 18: Write `NamespaceView`**

```tsx
import React, { useState } from 'react';
import { UnsTreeView } from '../home/UnsTreeView';
import { PayloadInspector } from '../home/PayloadInspector';
import { LiveMqttFeed } from '../home/LiveMqttFeed';
import { FindByProperty } from './FindByProperty';

/**
 * The graph of UNS Nodes, discovered from traffic.
 *
 * Separate from ASSETS on purpose: the Asset Model is authored and this is observed, so
 * a machine that has not published yet is absent here and present there. The header says
 * which of the two a reader is looking at, because the two look alike and mean opposite
 * things when a row is missing.
 */
export const NamespaceView: React.FC = () => {
  const [pane, setPane] = useState<'payload' | 'property'>('payload');

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="namespace-view">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[#E2E8F0] px-3 py-2 dark:border-[#1E293B]">
        <h1 className="text-[13px] font-bold text-[#0F172A] dark:text-[#E2E8F0]">Namespace</h1>
        <span className="text-[11px] text-[#64748B]">
          Discovered from published traffic. What is <em>authored</em> is under{' '}
          <a href="#/assets" className="text-sky-700 underline dark:text-sky-300">
            Assets
          </a>
          .
        </span>
        <span className="ml-auto flex items-center gap-1">
          {(
            [
              ['payload', 'Selected payload'],
              ['property', 'Find by payload key'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setPane(id)}
              aria-pressed={pane === id}
              className={`rounded px-2 py-0.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                pane === id
                  ? 'bg-[#1E293B] text-white dark:bg-[#E2E8F0] dark:text-[#0B0B0C]'
                  : 'text-[#64748B] hover:bg-[#F1F5F9] dark:hover:bg-[#1E293B]/40'
              }`}
            >
              {label}
            </button>
          ))}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-12">
        <section
          aria-label="Topic tree"
          className="col-span-3 min-h-0 overflow-hidden border-r border-[#E2E8F0] dark:border-[#1E293B]"
        >
          <UnsTreeView />
        </section>
        <section
          aria-label={pane === 'payload' ? 'Selected payload' : 'Find by payload key'}
          className="col-span-5 flex min-h-0 flex-col overflow-hidden border-r border-[#E2E8F0] dark:border-[#1E293B]"
        >
          {pane === 'payload' ? <PayloadInspector /> : <FindByProperty />}
        </section>
        <section aria-label="Live feed" className="col-span-4 min-h-0 overflow-hidden">
          <LiveMqttFeed />
        </section>
      </div>
    </div>
  );
};
```

The three-pane split is the layout `HomeView.tsx` already used, minus its mobile stacking — per the constraints this console is desktop-first at 1280px and above, and the panes scroll rather than the shell.

- [ ] **Step 19: Point the route at it and delete `HomeView`**

In `11_frontend/src/App.tsx`, replace the Task 1 placeholder for `/namespace` with `<NamespaceView />`. Then delete `11_frontend/src/components/home/HomeView.tsx`: `NamespaceView` replaces it, and `grep -rn "HomeView" src` must print nothing before the commit. Its three children stay where they are.

- [ ] **Step 20: Run everything**

```bash
cd 11_frontend && npx vitest run && npx tsc --noEmit && npm run lint
```

Expected: PASS. `grep -rn "isa95-probe\|HomeView" src` prints nothing.

- [ ] **Step 21: Commit**

```bash
git add 11_frontend/src/lib/uns/tree-search.ts 11_frontend/src/lib/uns/tree-search.test.ts \
        11_frontend/src/lib/uns/node-meta.ts 11_frontend/src/services/graphql/client.ts \
        11_frontend/src/services/graphql/client-tree.test.ts 11_frontend/src/context/UNSContext.tsx \
        11_frontend/src/components/home/ 11_frontend/src/components/namespace/ 11_frontend/src/App.tsx
git rm 11_frontend/src/lib/uns/isa95-probe.ts 11_frontend/src/components/home/HomeView.tsx
git commit -m "feat(frontend): namespace browsing that neither hides nor invents topics

Two defects in the topic tree. Typing in the search box hid every row that did not
match, so looking for one machine removed the plant around it; matches are now a list
above the tree and the tree's rows do not change. And when the Asset Model declared
nothing and a single-level query returned nothing, the tree filled the gap with
ProcessValue/Setpoint/Status/Alarm/EVENT and six sensor names taken from the simulator -
rows for topics that were never published. lib/uns/map-assets.ts already called that out
as wrong for every plant that is not the simulator and already replaced it with authored
Metric Definitions, so this deletes lib/uns/isa95-probe.ts and lets an empty branch be
empty.

Sparkplug is filtered out of tree roots and children: DEVICE is a label in both the UNS
and Sparkplug node-type sets, so the guarantee is worth making in one line.

getUnsNodesByProperty gets the screen the gap table gives it. It matches payload keys
rather than topic segments and takes no AND/OR/NOT operator, so the panel says the first
and offers no control for the second.

Text search covers the topics loaded in this browser and says so with the count. There is
no server-side topic search to call; that is marked requires backend."
```

---

---

## Task 18: HISTORIAN — the query the API actually supports, and a CSV of the rows on screen

This is spec section 18 test 13: *"**Historian by property** sends the OR/AND/NOT
combination the form expresses, and CSV export contains exactly the loaded rows."*

Seven facts from the repo set the whole shape of this task. Read them before writing code,
because five of them are defects and the task exists to remove them.

**1. The query has no row limit and no ordering.** `HistorianDBHelper._fetch`
(`07_uns_graphql/src/uns_graphql/backend/historian.py:115-175`) builds
`SELECT time, topic, client_id, mqtt_msg FROM <table> WHERE …` and executes it. There is no
`LIMIT`, no `OFFSET` and no `ORDER BY`. Two consequences, and the current UI gets both wrong:

- The footer at `explore/HistorianTable.tsx:219` says *"Pagination: Backend GraphQL schema
  returns single query batch (Pagination blocked pending GraphQL schema)"*. That reads as
  "the backend truncated your results and we cannot fetch page two". The opposite is true:
  every matching row is already here, and there is no page two to fetch. Replace the notice
  with the fact, and do not build a fake pager.
- Row order is whatever the database returns. The table renders rows in array order and
  labels the column `Timestamp`, which invites an operator to read the first row as the
  newest event. Sort in the view — and say the sort is the view's, not the historian's.

**2. `binaryOperator` means three specific things.** From `HistorianDBHelper` and the
resolver in `07_uns_graphql/src/uns_graphql/queries/historian.py`, property matching uses a
JSON path of the form `$.**."key"`, so a key matches **at any depth** in the payload, and:

| Operator | Matches an event when |
|---|---|
| `OR`  | any one of the keys is present |
| `AND` | all of the keys are present |
| `NOT` | none of the keys is present |

Topic and time filters are always ANDed on top. The form must say which of the three it is
sending in those words, because "NOT" alone reads as "not the first key".

**3. Only the historian query takes the operator.** `getHistoricEventsByProperty` has
`binaryOperator`; `getUnsNodesByProperty` does not (`queries/graph.py:312-347`). Task 17
moved the node-property search to NAMESPACE. This task deletes the fourth mode from the
historian form, which is the other half of that move.

**4. CSV exports a different row set than the header counts.** `handleExportCsv`
(`explore/HistorianTable.tsx:34-74`) iterates `events`, while the header at `:84` shows
`{filteredEvents.length} / {events.length} rows`. Type a filter, click Export, and you get
rows you cannot see. Spec test 13 says "exactly the loaded rows"; the fix is to export the
rows on screen and put that number in the button label, so the two readings of "loaded"
become the same number and the button cannot lie about it.

**5. The export button is gated by a permission that gates nothing.**
`canExport = hasPermission('export_csv')` renders a padlock and the title *"Export CSV
permission restricted by Administrator"* over rows that are already in the browser's
memory and already on the screen. Anyone can read them, select them, or open devtools. The
gate is theatre, so it goes. Real restriction would have to happen in the resolver, and no
query supports it — **requires backend**, out of scope for this cycle and for the
authentication cycle too, which gates mutations rather than reads.

**6. The form runs a query on every keystroke.** `ExploreView` closes `runQuery` over every
input value and then does `useEffect(() => { runQuery(); }, [runQuery])` (`:144-146`).
`runQuery`'s identity changes whenever any field changes, so each character typed into the
topic box fires another unbounded historian query. Combined with fact 1 that is a real
hazard, not just waste. The rebuilt screen queries on an explicit **Run query** and on a
deep link from `jumpToHistorian`, and on nothing else.

**7. A topic with no wildcard is silently rewritten.** `resolveHistorianTopic` appends `/#`
via `historianTopic` (`src/lib/uns/topics.ts:12`). On the broker side
`get_regex_for_topic_with_wildcard` (`02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py:374-398`)
maps `a/#` to `a(/.*)*` — the comment at `:389` states that `a/#` "should map to just `a`
too". So `Plant/Line1` is queried as `Plant/Line1/#`, which matches `Plant/Line1` **and**
everything beneath it. That is the behaviour an operator wants; it is also a rewrite of what
they typed, so the screen shows the resolved topic.

**One structural change.** Once `ExploreView` is deleted, `src/components/explore/` holds
only `HistorianTable` and `HistorianTrendChart`, both used solely by the Historian screen. A
directory named after a menu item that no longer exists is the same class of untruth as a
badge that lies, so both files move to `historian/` with `git mv`. Their bodies are
otherwise unchanged apart from the table's four fixes above; the trend chart is not touched
at all beyond its import paths, and it stays a native chart rather than a Grafana embed
because it plots exactly the rows the query returned — no bucketing, no server-side
aggregation, nothing to be wrong about. (Task 11's PLANT ▸ Trend embeds Grafana instead,
because that surface trends a Metric over a range the browser never loads.)

**Files:**
- Create: `11_frontend/src/lib/csv/to-csv.ts`
- Create: `11_frontend/src/lib/csv/to-csv.test.ts`
- Create: `11_frontend/src/lib/uns/historian-query.ts`
- Create: `11_frontend/src/lib/uns/historian-query.test.ts`
- Create: `11_frontend/src/lib/uns/historian-csv.ts`
- Create: `11_frontend/src/lib/uns/historian-csv.test.ts`
- Create: `11_frontend/src/components/historian/HistorianQueryForm.tsx`
- Create: `11_frontend/src/components/historian/HistorianView.tsx`
- Create: `11_frontend/src/components/historian/HistorianView.test.tsx`
- Create: `11_frontend/src/components/historian/HistorianTable.test.tsx`
- Move + modify: `11_frontend/src/components/explore/HistorianTable.tsx` →
  `11_frontend/src/components/historian/HistorianTable.tsx` (`:1-20` imports and the
  permission gate, `:33-74` the export, `:84` the row count, `:101-116` the button,
  `:215-222` the footer)
- Move: `11_frontend/src/components/explore/HistorianTrendChart.tsx` →
  `11_frontend/src/components/historian/HistorianTrendChart.tsx` (import paths only)
- Delete: `11_frontend/src/components/explore/ExploreView.tsx`
- Modify: `11_frontend/src/App.tsx` (the `/historian` route from Task 1)

**Interfaces:**
- Consumes:
  - `unsGraphQLClient.getHistoricEvents(topic: string, fromTime?: string, toTime?: string): Promise<HistoricEvent[]>`,
    `.getHistoricEventsByPublishers(publishers: string[], topics?: string[], fromTime?: string, toTime?: string): Promise<HistoricEvent[]>`,
    `.getHistoricEventsByProperty(propertyKeys: string[], binaryOperator?: BinaryOperator, topics?: string[], fromTime?: string, toTime?: string): Promise<HistoricEvent[]>`
    — all three exist today at `src/services/graphql/client.ts` and all three `throw` on a
    transport error rather than returning a result object. Confirm the parameter order in
    the file before wiring the calls; do not change their signatures.
  - `historianTopic` from `src/lib/uns/topics.ts`.
  - `HistoricEvent`, `BinaryOperator` from `src/types/uns.ts`.
  - `useUNS()` for `historianInitialTopic` and `selectedNode` (Task 1 left both in place).
  - `StatusPill` from Task 5.
- Produces:
  ```ts
  // src/lib/csv/to-csv.ts — domain-free, so nothing about UNS leaks into the serialiser
  export interface CsvColumn<T> {
    header: string;
    value: (row: T) => unknown;
  }
  /** RFC 4180: CRLF rows, quotes doubled, a field quoted only when it needs to be. */
  export function toCsv<T>(columns: CsvColumn<T>[], rows: T[]): string;
  /** Triggers a browser download. Prepends a BOM so Excel reads the file as UTF-8. */
  export function downloadCsv(filename: string, csv: string): void;
  ```
  ```ts
  // src/lib/uns/historian-query.ts — the form's state, and the pure functions over it
  export type HistorianMode = 'topic-time' | 'publisher' | 'payload-key';
  export type TimePreset = '5m' | '15m' | '1h' | '6h' | '24h' | 'all' | 'custom';

  export interface HistorianQuery {
    mode: HistorianMode;
    topic: string;
    publishers: string;
    propertyKeys: string;
    operator: BinaryOperator;
    preset: TimePreset;
    /** `datetime-local` values, i.e. 'YYYY-MM-DDTHH:mm' in the browser's zone. */
    customStart: string;
    customEnd: string;
  }

  export const MODE_LABELS: Record<HistorianMode, string>;
  export const OPERATOR_MEANING: Record<BinaryOperator, string>;
  export function defaultQuery(topic: string, now: number): HistorianQuery;
  export function timeBounds(query: HistorianQuery, now: number): { start?: string; end?: string };
  export function resolveHistorianTopic(topic: string): string;
  export function parseList(input: string): string[];
  ```
  ```ts
  // src/lib/uns/historian-csv.ts
  export function payloadKeys(rows: HistoricEvent[]): string[];
  export function historianCsvColumns(rows: HistoricEvent[]): CsvColumn<HistoricEvent>[];
  export function historianCsvFilename(now: Date): string;
  ```
  ```tsx
  // src/components/historian/HistorianQueryForm.tsx — presentational only
  export const HistorianQueryForm: React.FC<{
    query: HistorianQuery;
    onChange: (next: HistorianQuery) => void;
    onRun: () => void;
    loading: boolean;
    error: string | null;
  }>;
  ```
  ```tsx
  // src/components/historian/HistorianView.tsx
  export const HistorianView: React.FC;
  // src/components/historian/HistorianTable.tsx — `topicTitle` dropped, it was never read
  export const HistorianTable: React.FC<{ events: HistoricEvent[]; isLoading: boolean }>;
  ```

- [ ] **Step 1: Write the failing CSV serialiser test**

Create `11_frontend/src/lib/csv/to-csv.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { CsvColumn, toCsv } from './to-csv';

interface Row {
  topic: string;
  value: unknown;
}

const columns: CsvColumn<Row>[] = [
  { header: 'topic', value: (r) => r.topic },
  { header: 'value', value: (r) => r.value },
];

describe('toCsv', () => {
  it('writes a header row and one row per input, separated by CRLF', () => {
    const csv = toCsv(columns, [
      { topic: 'a/b', value: 1 },
      { topic: 'a/c', value: 2 },
    ]);
    expect(csv).toBe('topic,value\r\na/b,1\r\na/c,2');
  });

  it('writes only the header when there are no rows', () => {
    expect(toCsv(columns, [])).toBe('topic,value');
  });

  it('quotes a field containing a comma, a quote or a newline, and doubles quotes', () => {
    const csv = toCsv(columns, [
      { topic: 'a,b', value: 'say "hi"' },
      { topic: 'multi\nline', value: 'plain' },
    ]);
    expect(csv).toBe('topic,value\r\n"a,b","say ""hi"""\r\n"multi\nline",plain');
  });

  it('leaves an ordinary field unquoted', () => {
    expect(toCsv(columns, [{ topic: 'a/b/c', value: 12.5 }])).toContain('a/b/c,12.5');
  });

  it('writes an empty field for null and undefined, not the words', () => {
    const csv = toCsv(columns, [{ topic: 'a', value: null }, { topic: 'b', value: undefined }]);
    expect(csv).toBe('topic,value\r\na,\r\nb,');
  });

  it('serialises an object field as JSON in one cell', () => {
    const csv = toCsv(columns, [{ topic: 'a', value: { x: 1, y: 'z' } }]);
    expect(csv).toBe('topic,value\r\na,"{""x"":1,""y"":""z""}"');
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/csv/to-csv.test.ts
```

Expected: FAIL — `Failed to resolve import "./to-csv"`.

- [ ] **Step 3: Write the serialiser**

Create `11_frontend/src/lib/csv/to-csv.ts`:

```ts
export interface CsvColumn<T> {
  header: string;
  value: (row: T) => unknown;
}

/** A field needs quoting only if it contains the delimiter, a quote, or a line break. */
const NEEDS_QUOTING = /[",\r\n]/;

function field(value: unknown): string {
  if (value === null || value === undefined) return '';
  const raw = typeof value === 'object' ? JSON.stringify(value) : String(value);
  return NEEDS_QUOTING.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

/** RFC 4180: CRLF rows, quotes doubled, a field quoted only when it needs to be. */
export function toCsv<T>(columns: CsvColumn<T>[], rows: T[]): string {
  const lines = [columns.map((column) => field(column.header)).join(',')];
  for (const row of rows) {
    lines.push(columns.map((column) => field(column.value(row))).join(','));
  }
  return lines.join('\r\n');
}

/** Triggers a browser download. Prepends a BOM so Excel reads the file as UTF-8. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // The old implementation never revoked, so every export leaked a blob for the
  // lifetime of the tab.
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run it and watch it pass**

```bash
cd 11_frontend && npx vitest run src/lib/csv/to-csv.test.ts
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Write the failing query-state test**

Create `11_frontend/src/lib/uns/historian-query.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  defaultQuery,
  parseList,
  resolveHistorianTopic,
  timeBounds,
  MODE_LABELS,
  OPERATOR_MEANING,
} from './historian-query';

const NOW = Date.parse('2026-09-02T12:00:00.000Z');

describe('resolveHistorianTopic', () => {
  it('appends /# to a topic with no wildcard, which also matches the topic itself', () => {
    expect(resolveHistorianTopic('CovestroAG/Dormagen/Line1')).toBe('CovestroAG/Dormagen/Line1/#');
  });

  it('leaves a topic that already has a wildcard alone', () => {
    expect(resolveHistorianTopic('CovestroAG/#')).toBe('CovestroAG/#');
    expect(resolveHistorianTopic('CovestroAG/+/Line1')).toBe('CovestroAG/+/Line1');
  });

  it('trims, and returns empty for blank input', () => {
    expect(resolveHistorianTopic('  a/b  ')).toBe('a/b/#');
    expect(resolveHistorianTopic('   ')).toBe('');
  });
});

describe('timeBounds', () => {
  it('turns a preset into an ISO window ending now', () => {
    const bounds = timeBounds({ ...defaultQuery('', NOW), preset: '15m' }, NOW);
    expect(bounds).toEqual({
      start: '2026-09-02T11:45:00.000Z',
      end: '2026-09-02T12:00:00.000Z',
    });
  });

  it('sends no bounds for the all-time preset', () => {
    expect(timeBounds({ ...defaultQuery('', NOW), preset: 'all' }, NOW)).toEqual({});
  });

  it('converts the custom local values to ISO', () => {
    const bounds = timeBounds(
      {
        ...defaultQuery('', NOW),
        preset: 'custom',
        customStart: '2026-09-01T08:00',
        customEnd: '2026-09-01T09:30',
      },
      NOW,
    );
    expect(bounds.start).toBe(new Date('2026-09-01T08:00').toISOString());
    expect(bounds.end).toBe(new Date('2026-09-01T09:30').toISOString());
  });

  it('drops an unparseable custom bound rather than sending "Invalid Date"', () => {
    const bounds = timeBounds(
      { ...defaultQuery('', NOW), preset: 'custom', customStart: '', customEnd: '' },
      NOW,
    );
    expect(bounds).toEqual({});
  });
});

describe('parseList', () => {
  it('splits on commas and drops blanks', () => {
    expect(parseList(' site , cell_id ,, ')).toEqual(['site', 'cell_id']);
  });

  it('returns an empty array for an empty string', () => {
    expect(parseList('   ')).toEqual([]);
  });
});

describe('the labels an operator reads', () => {
  it('names the three modes in plain language, not in GraphQL field names', () => {
    expect(Object.values(MODE_LABELS)).toEqual(['By topic and time', 'By publisher', 'By payload key']);
    expect(Object.values(MODE_LABELS).join(' ')).not.toMatch(/getHistoric/);
  });

  it('spells out what each operator does to the result', () => {
    expect(OPERATOR_MEANING.OR).toBe('any of these keys is present');
    expect(OPERATOR_MEANING.AND).toBe('all of these keys are present');
    expect(OPERATOR_MEANING.NOT).toBe('none of these keys is present');
  });
});

describe('defaultQuery', () => {
  it('starts on topic and time, over the last hour, with the topic it was given', () => {
    const query = defaultQuery('CovestroAG/Dormagen', NOW);
    expect(query.mode).toBe('topic-time');
    expect(query.preset).toBe('1h');
    expect(query.topic).toBe('CovestroAG/Dormagen');
    expect(query.operator).toBe('OR');
  });
});
```

The two `custom` assertions compare against `new Date(...)` rather than a literal because
`datetime-local` values have no zone and the suite must pass in any `TZ`.

- [ ] **Step 6: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/uns/historian-query.test.ts
```

Expected: FAIL — `Failed to resolve import "./historian-query"`.

- [ ] **Step 7: Write the query-state module**

Create `11_frontend/src/lib/uns/historian-query.ts`:

```ts
import { BinaryOperator } from '../../types/uns';
import { historianTopic } from './topics';

export type HistorianMode = 'topic-time' | 'publisher' | 'payload-key';
export type TimePreset = '5m' | '15m' | '1h' | '6h' | '24h' | 'all' | 'custom';

export interface HistorianQuery {
  mode: HistorianMode;
  topic: string;
  publishers: string;
  propertyKeys: string;
  operator: BinaryOperator;
  preset: TimePreset;
  /** `datetime-local` values, i.e. 'YYYY-MM-DDTHH:mm' in the browser's zone. */
  customStart: string;
  customEnd: string;
}

/** Operators are the resolver's, labels are the operator's. Never show the field name. */
export const MODE_LABELS: Record<HistorianMode, string> = {
  'topic-time': 'By topic and time',
  publisher: 'By publisher',
  'payload-key': 'By payload key',
};

/**
 * What `binaryOperator` does to the result set, in the resolver's own terms: a key is
 * matched at any depth in the payload, and the topic and time filters are ANDed on top.
 */
export const OPERATOR_MEANING: Record<BinaryOperator, string> = {
  OR: 'any of these keys is present',
  AND: 'all of these keys are present',
  NOT: 'none of these keys is present',
};

const PRESET_MS: Record<Exclude<TimePreset, 'all' | 'custom'>, number> = {
  '5m': 5 * 60 * 1000,
  '15m': 15 * 60 * 1000,
  '1h': 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
};

/** Local `datetime-local` string for a moment, so the custom pickers open somewhere sane. */
function localInputValue(ms: number): string {
  const at = new Date(ms);
  const offset = at.getTimezoneOffset() * 60 * 1000;
  return new Date(ms - offset).toISOString().slice(0, 16);
}

export function defaultQuery(topic: string, now: number): HistorianQuery {
  return {
    mode: 'topic-time',
    topic,
    publishers: '',
    propertyKeys: '',
    operator: 'OR',
    preset: '1h',
    customStart: localInputValue(now - PRESET_MS['1h']),
    customEnd: localInputValue(now),
  };
}

function isoOrUndefined(value: string): string | undefined {
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString();
}

export function timeBounds(query: HistorianQuery, now: number): { start?: string; end?: string } {
  if (query.preset === 'all') return {};
  if (query.preset === 'custom') {
    const start = isoOrUndefined(query.customStart);
    const end = isoOrUndefined(query.customEnd);
    // An omitted bound is an omitted filter, not an "Invalid Date" the resolver rejects.
    return { ...(start ? { start } : {}), ...(end ? { end } : {}) };
  }
  return {
    start: new Date(now - PRESET_MS[query.preset]).toISOString(),
    end: new Date(now).toISOString(),
  };
}

/**
 * A topic with no wildcard is queried as `topic/#`. The broker's own regex maps `a/#` to
 * `a(/.*)*`, so that form matches `a` itself as well as everything under it
 * (`02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py:374-398`).
 */
export function resolveHistorianTopic(topic: string): string {
  const trimmed = topic.trim();
  if (!trimmed || trimmed.includes('#') || trimmed.includes('+')) return trimmed;
  return historianTopic(trimmed);
}

export function parseList(input: string): string[] {
  return input
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}
```

- [ ] **Step 8: Run it and watch it pass**

```bash
cd 11_frontend && npx vitest run src/lib/uns/historian-query.test.ts
```

Expected: PASS, 11 tests.

- [ ] **Step 9: Write the failing CSV-columns test**

Create `11_frontend/src/lib/uns/historian-csv.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { HistoricEvent } from '../../types/uns';
import { historianCsvColumns, historianCsvFilename, payloadKeys } from './historian-csv';
import { toCsv } from '../csv/to-csv';

const ROWS: HistoricEvent[] = [
  {
    id: 'e1',
    topic: 'CovestroAG/Dormagen/Line1/Reactor',
    publisher: 'edge:s7',
    timestamp: '2026-09-02T11:59:00.000Z',
    payload: { temperature: 71.2, unit: 'C' },
  },
  {
    id: 'e2',
    topic: 'CovestroAG/Dormagen/Line1/Pump',
    publisher: null,
    timestamp: '2026-09-02T11:58:00.000Z',
    payload: { pressure: 4.1 },
  },
];

describe('payloadKeys', () => {
  it('unions the top-level keys across the rows, sorted', () => {
    expect(payloadKeys(ROWS)).toEqual(['pressure', 'temperature', 'unit']);
  });

  it('ignores a payload that is not a plain object', () => {
    expect(
      payloadKeys([
        { ...ROWS[0], payload: 'raw string' as unknown as Record<string, unknown> },
        { ...ROWS[1], payload: [1, 2] as unknown as Record<string, unknown> },
      ]),
    ).toEqual([]);
  });
});

describe('historianCsvColumns', () => {
  it('leads with the four columns the historian row has, then one per payload key', () => {
    expect(historianCsvColumns(ROWS).map((column) => column.header)).toEqual([
      'timestamp',
      'topic',
      'publisher',
      'payload',
      'pressure',
      'temperature',
      'unit',
    ]);
  });

  it('leaves a key absent from a row empty instead of writing 0', () => {
    const csv = toCsv(historianCsvColumns(ROWS), ROWS).split('\r\n');
    expect(csv[2]).toBe(
      '2026-09-02T11:58:00.000Z,CovestroAG/Dormagen/Line1/Pump,,"{""pressure"":4.1}",4.1,,',
    );
  });

  it('keeps the whole payload in one cell so a nested value is never lost', () => {
    const nested: HistoricEvent = {
      ...ROWS[0],
      payload: { outer: { inner: 5 } },
    };
    const csv = toCsv(historianCsvColumns([nested]), [nested]);
    expect(csv).toContain('"{""outer"":{""inner"":5}}"');
  });
});

describe('historianCsvFilename', () => {
  it('stamps the file with the moment of export, to the second', () => {
    expect(historianCsvFilename(new Date('2026-09-02T12:00:05.000Z'))).toBe(
      'historic-events-2026-09-02T12-00-05Z.csv',
    );
  });
});
```

- [ ] **Step 10: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/lib/uns/historian-csv.test.ts
```

Expected: FAIL — `Failed to resolve import "./historian-csv"`.

- [ ] **Step 11: Write the CSV columns**

Create `11_frontend/src/lib/uns/historian-csv.ts`:

```ts
import { CsvColumn } from '../csv/to-csv';
import { HistoricEvent } from '../../types/uns';

function asRecord(payload: unknown): Record<string, unknown> | null {
  return payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>)
    : null;
}

/**
 * The historian's own columns. `id` is deliberately absent: the SELECT reads
 * `time, topic, client_id, mqtt_msg` and nothing else, so the `id` on `HistoricEvent` is
 * assigned by this client. Exporting it would imply a row identity the store does not have.
 */
const HISTORIAN_COLUMNS: CsvColumn<HistoricEvent>[] = [
  { header: 'timestamp', value: (event) => event.timestamp },
  { header: 'topic', value: (event) => event.topic },
  { header: 'publisher', value: (event) => event.publisher },
  { header: 'payload', value: (event) => event.payload },
];

/** Top-level payload keys across the given rows, so the export widens to the data. */
export function payloadKeys(rows: HistoricEvent[]): string[] {
  const keys = new Set<string>();
  for (const row of rows) {
    const record = asRecord(row.payload);
    if (record) Object.keys(record).forEach((key) => keys.add(key));
  }
  return Array.from(keys).sort();
}

export function historianCsvColumns(rows: HistoricEvent[]): CsvColumn<HistoricEvent>[] {
  return [
    ...HISTORIAN_COLUMNS,
    ...payloadKeys(rows).map((key) => ({
      header: key,
      value: (event: HistoricEvent) => asRecord(event.payload)?.[key],
    })),
  ];
}

export function historianCsvFilename(now: Date): string {
  const stamp = now.toISOString().slice(0, 19).replace(/:/g, '-');
  return `historic-events-${stamp}Z.csv`;
}
```

- [ ] **Step 12: Run it and watch it pass**

```bash
cd 11_frontend && npx vitest run src/lib/uns/historian-csv.test.ts
```

Expected: PASS, 5 tests. If the `publisher: null` row writes the word `null` rather than an
empty cell, `field` in `to-csv.ts` is wrong, not this module.

- [ ] **Step 13: Commit the three pure modules**

```bash
git add 11_frontend/src/lib/csv 11_frontend/src/lib/uns/historian-query.ts \
  11_frontend/src/lib/uns/historian-query.test.ts \
  11_frontend/src/lib/uns/historian-csv.ts 11_frontend/src/lib/uns/historian-csv.test.ts
git commit -m "feat(frontend): CSV serialiser and historian query state

Three pure modules the Historian screen builds on: an RFC 4180 serialiser, the
form state with the time-bound and /# rewrite rules, and the historian's CSV
columns. The operator meanings are the resolver's OR/AND/NOT semantics spelled
out in words."
```

- [ ] **Step 14: Move the two kept components**

```bash
cd 11_frontend
mkdir -p src/components/historian
git mv src/components/explore/HistorianTable.tsx src/components/historian/HistorianTable.tsx
git mv src/components/explore/HistorianTrendChart.tsx src/components/historian/HistorianTrendChart.tsx
```

Both files import from `'../../types/uns'`, `'../common/JsonViewer'`, `'../../context/UNSContext'`
and `'../../lib/uns/telemetry-metrics'`. The nesting depth is unchanged, so **no import path
changes**. Verify rather than assume:

```bash
cd 11_frontend && npx tsc --noEmit 2>&1 | grep -i "historian" || echo "no historian import errors"
```

`ExploreView.tsx` still imports from `./HistorianTable`, which is now gone, so `tsc` will
report that one file. That is expected and Step 22 deletes it.

- [ ] **Step 15: Write the failing table test**

Create `11_frontend/src/components/historian/HistorianTable.test.tsx`. It mocks only
`downloadCsv` and keeps the real `toCsv`, so the assertion runs over the bytes an operator
would actually receive. That also keeps `URL.createObjectURL` out of the test, which jsdom
does not implement.

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HistoricEvent } from '../../types/uns';

const downloaded: { name: string; csv: string }[] = [];

vi.mock('../../lib/csv/to-csv', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/csv/to-csv')>();
  return {
    ...actual,
    downloadCsv: (name: string, csv: string) => {
      downloaded.push({ name, csv });
    },
  };
});

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({ jumpToTopicInTree: vi.fn() }),
}));

import { HistorianTable } from './HistorianTable';

const EVENTS: HistoricEvent[] = [
  {
    id: 'e1',
    topic: 'CovestroAG/Dormagen/Line1/Reactor',
    publisher: 'edge:s7',
    timestamp: '2026-09-02T11:59:00.000Z',
    payload: { temperature: 71.2 },
  },
  {
    id: 'e2',
    topic: 'CovestroAG/Dormagen/Line1/Pump',
    publisher: 'edge:s7',
    timestamp: '2026-09-02T11:58:00.000Z',
    payload: { pressure: 4.1 },
  },
  {
    id: 'e3',
    topic: 'CovestroAG/Krefeld/Line9/Reactor',
    publisher: 'edge:beckhoff',
    timestamp: '2026-09-02T11:57:00.000Z',
    payload: { temperature: 68.4 },
  },
];

describe('HistorianTable', () => {
  beforeEach(() => {
    downloaded.length = 0;
  });

  it('exports exactly the rows on screen, not every row loaded', async () => {
    const user = userEvent.setup();
    render(<HistorianTable events={EVENTS} isLoading={false} />);

    await user.type(screen.getByRole('textbox', { name: /filter rows/i }), 'Krefeld');
    expect(screen.getByTestId('historian-row-count')).toHaveTextContent('1 of 3 rows shown');

    await user.click(screen.getByRole('button', { name: 'Export 1 row to CSV' }));

    expect(downloaded).toHaveLength(1);
    const lines = downloaded[0].csv.split('\r\n');
    expect(lines).toHaveLength(2);
    expect(lines[1]).toContain('CovestroAG/Krefeld/Line9/Reactor');
    expect(downloaded[0].csv).not.toContain('Dormagen');
  });

  it('names the row count in the button so the two cannot drift apart', () => {
    render(<HistorianTable events={EVENTS} isLoading={false} />);
    expect(screen.getByRole('button', { name: 'Export 3 rows to CSV' })).toBeEnabled();
  });

  it('disables the export only when there is nothing on screen', () => {
    render(<HistorianTable events={[]} isLoading={false} />);
    expect(screen.getByRole('button', { name: /export/i })).toBeDisabled();
  });

  it('does not gate the export behind a permission over rows already rendered', () => {
    render(<HistorianTable events={EVENTS} isLoading={false} />);
    expect(screen.queryByTitle(/restricted by administrator/i)).toBeNull();
  });

  it('states that every matching row arrived, instead of claiming pagination is blocked', () => {
    render(<HistorianTable events={EVENTS} isLoading={false} />);
    const footer = screen.getByTestId('historian-footer');
    expect(footer).toHaveTextContent('no row limit');
    expect(footer).toHaveTextContent('All 3 matching rows arrived in one response');
    expect(footer).not.toHaveTextContent(/pagination/i);
    expect(screen.queryByRole('button', { name: /next page/i })).toBeNull();
  });
});
```

- [ ] **Step 16: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/historian/HistorianTable.test.tsx
```

Expected: FAIL. The filter input has no accessible name, the button reads `Export CSV`, and
`historian-row-count` / `historian-footer` do not exist.

- [ ] **Step 17: Fix the four defects in the table**

In `11_frontend/src/components/historian/HistorianTable.tsx`, replace the imports and the
top of the component (`:1-74`) with:

```tsx
import React, { useMemo, useState } from 'react';
import { Download, ChevronDown, ChevronRight, Search, FileSpreadsheet, ExternalLink } from 'lucide-react';
import { HistoricEvent } from '../../types/uns';
import { JsonViewer } from '../common/JsonViewer';
import { useUNS } from '../../context/UNSContext';
import { downloadCsv, toCsv } from '../../lib/csv/to-csv';
import { historianCsvColumns, historianCsvFilename } from '../../lib/uns/historian-csv';

interface HistorianTableProps {
  events: HistoricEvent[];
  isLoading: boolean;
}

export const HistorianTable: React.FC<HistorianTableProps> = ({ events, isLoading }) => {
  const { jumpToTopicInTree } = useUNS();
  const [filterText, setFilterText] = useState('');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  const visibleRows = useMemo(() => {
    if (!filterText) return events;
    const query = filterText.toLowerCase();
    return events.filter(
      (event) =>
        event.topic.toLowerCase().includes(query) ||
        (event.publisher ?? '').toLowerCase().includes(query) ||
        JSON.stringify(event.payload).toLowerCase().includes(query),
    );
  }, [events, filterText]);

  // Exactly the rows on screen. The button label carries the same number, so a filtered
  // export cannot quietly hand over rows the operator never saw.
  const handleExportCsv = () => {
    if (visibleRows.length === 0) return;
    downloadCsv(
      historianCsvFilename(new Date()),
      toCsv(historianCsvColumns(visibleRows), visibleRows),
    );
  };

  const exportLabel = `Export ${visibleRows.length} ${visibleRows.length === 1 ? 'row' : 'rows'} to CSV`;
```

Then replace the header controls (the old `:79-117`) with:

```tsx
  return (
    <div
      id="historian-table-container"
      className="flex flex-col overflow-hidden rounded-lg border border-[#E2E8F0] bg-white dark:border-[#1E293B] dark:bg-[#111114]"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E2E8F0] bg-white p-3 text-[12px] dark:border-[#1E293B] dark:bg-[#111114]">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-emerald-600 dark:text-[#10B981]" />
          <span className="text-[12px] font-semibold text-[#0F172A] dark:text-[#F8FAFC]">Historic Events</span>
          <span
            data-testid="historian-row-count"
            className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[11px] text-[#475569] dark:bg-[#1E293B] dark:text-[#94A3B8]"
          >
            {visibleRows.length} of {events.length} rows shown
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <label htmlFor="historian-filter" className="sr-only">
              Filter rows
            </label>
            <Search className="pointer-events-none absolute left-2 top-2 h-3 w-3 text-[#64748B]" />
            <input
              id="historian-filter"
              type="text"
              placeholder="Topic, publisher or payload"
              value={filterText}
              onChange={(event) => setFilterText(event.target.value)}
              className="w-44 rounded border border-[#CBD5E1] bg-[#F8FAFC] py-1 pl-7 pr-2 font-mono text-[11px] text-[#0F172A] placeholder-[#64748B] focus:border-amber-500 focus:outline-none sm:w-56 dark:border-[#1E293B] dark:bg-[#0B0B0C] dark:text-[#F8FAFC] dark:focus:border-[#FFC107]"
            />
          </div>

          <button
            id="export-historian-csv-btn"
            type="button"
            onClick={handleExportCsv}
            disabled={visibleRows.length === 0}
            className="flex cursor-pointer items-center gap-1 rounded border border-[#10B981]/40 bg-[#10B981]/15 px-2.5 py-1 font-mono text-[11px] font-medium text-[#0F9D63] transition-colors hover:bg-[#10B981]/25 disabled:cursor-not-allowed disabled:opacity-40 dark:text-[#10B981]"
          >
            <Download className="h-3.5 w-3.5" />
            <span>{exportLabel}</span>
          </button>
        </div>
      </div>
```

The rest of the table body is unchanged except that every `filteredEvents` becomes
`visibleRows`, the loading line reads `Reading Historic Events…` instead of
`Querying Timescale historian records...`, and the empty line reads:

```tsx
              <tr>
                <td colSpan={6} className="py-8 text-center text-[#64748B]">
                  <p>No Historic Events matched this query.</p>
                  <p className="mt-1 text-[11px] text-[#94A3B8]">
                    Widen the time range, or check that this topic is being published.
                  </p>
                </td>
              </tr>
```

Finally replace the footer (the old `:215-222`):

```tsx
      <div
        data-testid="historian-footer"
        className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E2E8F0] bg-[#F8FAFC] p-2.5 font-mono text-[11px] text-[#64748B] dark:border-[#1E293B] dark:bg-[#0B0B0C]"
      >
        {/* The historian SELECT has no LIMIT and no OFFSET, so there is no page two to
            fetch and no pager to build. Say so rather than implying a truncated result. */}
        <span>
          This query has no row limit. All {events.length} matching rows arrived in one response.
        </span>
        <span>Export writes the {visibleRows.length} rows shown.</span>
      </div>
```

Delete the `useAuth` import, the `hasPermission` call, the `canExport` constant and the
`Lock` import. `Lock` is no longer used anywhere in this file, so leaving it would fail lint.

- [ ] **Step 18: Run it and watch it pass**

```bash
cd 11_frontend && npx vitest run src/components/historian/HistorianTable.test.tsx
```

Expected: PASS, 5 tests.

- [ ] **Step 19: Write the failing view test**

Create `11_frontend/src/components/historian/HistorianView.test.tsx`. This is spec test 13's
operator half. The table and the chart are mocked, so the assertions are about what the view
sends and in what order it hands rows over.

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HistoricEvent } from '../../types/uns';

const getHistoricEvents = vi.fn();
const getHistoricEventsByPublishers = vi.fn();
const getHistoricEventsByProperty = vi.fn();

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getHistoricEvents: (...args: unknown[]) => getHistoricEvents(...args),
    getHistoricEventsByPublishers: (...args: unknown[]) => getHistoricEventsByPublishers(...args),
    getHistoricEventsByProperty: (...args: unknown[]) => getHistoricEventsByProperty(...args),
  },
}));

const unsContext = { historianInitialTopic: '', selectedNode: null as { topic: string } | null };
vi.mock('../../context/UNSContext', () => ({ useUNS: () => unsContext }));

vi.mock('./HistorianTable', () => ({
  HistorianTable: ({ events, isLoading }: { events: HistoricEvent[]; isLoading: boolean }) => (
    <div data-testid="table">{isLoading ? 'loading' : events.map((event) => event.id).join(',')}</div>
  ),
}));

vi.mock('./HistorianTrendChart', () => ({
  HistorianTrendChart: () => <div data-testid="chart" />,
}));

import { HistorianView } from './HistorianView';

const NOW = new Date('2026-09-02T12:00:00.000Z');
const START = '2026-09-02T11:00:00.000Z';
const END = '2026-09-02T12:00:00.000Z';

const event = (id: string, timestamp: string): HistoricEvent => ({
  id,
  topic: 'CovestroAG/Dormagen/Line1',
  publisher: 'edge:s7',
  timestamp,
  payload: { value: 1 },
});

const setup = () => {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  render(<HistorianView />);
  return user;
};

describe('HistorianView', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    unsContext.historianInitialTopic = '';
    unsContext.selectedNode = null;
    getHistoricEvents.mockReset().mockResolvedValue([]);
    getHistoricEventsByPublishers.mockReset().mockResolvedValue([]);
    getHistoricEventsByProperty.mockReset().mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('names the three modes in plain language', () => {
    setup();
    expect(screen.getByRole('button', { name: 'By topic and time' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'By publisher' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'By payload key' })).toBeInTheDocument();
    expect(screen.queryByText(/getHistoricEvents/)).toBeNull();
    expect(screen.queryByText(/getUnsNodesByProperty/)).toBeNull();
  });

  it('does not query while the operator is still typing', async () => {
    const user = setup();
    await user.type(screen.getByRole('textbox', { name: /topic/i }), 'CovestroAG/Dormagen');
    expect(getHistoricEvents).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /run query/i }));
    expect(getHistoricEvents).toHaveBeenCalledTimes(1);
  });

  it('discloses that a wildcard-free topic is queried as topic/#', async () => {
    const user = setup();
    await user.type(screen.getByRole('textbox', { name: /topic/i }), 'CovestroAG/Dormagen');
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(getHistoricEvents).toHaveBeenCalledWith('CovestroAG/Dormagen/#', START, END);
    expect(screen.getByTestId('historian-topic-note')).toHaveTextContent(
      'Queried as CovestroAG/Dormagen/# — which also matches CovestroAG/Dormagen itself.',
    );
  });

  it.each([
    ['any of these keys is present', 'OR'],
    ['all of these keys are present', 'AND'],
    ['none of these keys is present', 'NOT'],
  ])('sends %s as binaryOperator %s', async (meaning, operator) => {
    const user = setup();
    await user.click(screen.getByRole('button', { name: 'By payload key' }));
    await user.type(screen.getByRole('textbox', { name: /payload keys/i }), 'site, cell_id');
    await user.selectOptions(screen.getByRole('combobox', { name: /match/i }), operator);
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(getHistoricEventsByProperty).toHaveBeenCalledWith(
      ['site', 'cell_id'],
      operator,
      undefined,
      START,
      END,
    );
    expect(screen.getByRole('combobox', { name: /match/i })).toHaveAccessibleDescription(
      new RegExp(meaning),
    );
  });

  it('sends the publisher list split on commas', async () => {
    const user = setup();
    await user.click(screen.getByRole('button', { name: 'By publisher' }));
    await user.type(screen.getByRole('textbox', { name: /publishers/i }), 'edge:s7, edge:beckhoff');
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(getHistoricEventsByPublishers).toHaveBeenCalledWith(
      ['edge:s7', 'edge:beckhoff'],
      undefined,
      START,
      END,
    );
  });

  it('sorts rows newest first, because the historian query has no ORDER BY', async () => {
    getHistoricEvents.mockResolvedValue([
      event('old', '2026-09-02T11:10:00.000Z'),
      event('new', '2026-09-02T11:50:00.000Z'),
      event('mid', '2026-09-02T11:30:00.000Z'),
    ]);
    const user = setup();
    await user.type(screen.getByRole('textbox', { name: /topic/i }), 'a/b');
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(await screen.findByTestId('table')).toHaveTextContent('new,mid,old');
    expect(screen.getByTestId('historian-order-note')).toHaveTextContent('Sorted newest first');
  });

  it('refuses to run an empty topic and says what to enter', async () => {
    const user = setup();
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(getHistoricEvents).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/enter a topic/i);
  });

  it('shows the transport error and clears the rows', async () => {
    getHistoricEvents.mockRejectedValue(new Error('GraphQL endpoint unreachable'));
    const user = setup();
    await user.type(screen.getByRole('textbox', { name: /topic/i }), 'a/b');
    await user.click(screen.getByRole('button', { name: /run query/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('GraphQL endpoint unreachable');
    expect(screen.getByTestId('table')).toHaveTextContent('');
  });

  it('warns that the query has no row limit before it is run', () => {
    setup();
    expect(screen.getByTestId('historian-no-limit-note')).toHaveTextContent(
      'no row limit',
    );
  });

  it('runs once for a topic arriving from another screen', async () => {
    unsContext.historianInitialTopic = 'CovestroAG/Krefeld/Line9';
    setup();
    await vi.waitFor(() =>
      expect(getHistoricEvents).toHaveBeenCalledWith('CovestroAG/Krefeld/Line9/#', START, END),
    );
    expect(getHistoricEvents).toHaveBeenCalledTimes(1);
  });
});
```

`vi.useFakeTimers({ shouldAdvanceTime: true })` plus `advanceTimers` on the `userEvent`
setup is what lets a pinned clock coexist with `userEvent`'s internal delays; without it
every `await user.type` hangs.

- [ ] **Step 20: Run it and watch it fail**

```bash
cd 11_frontend && npx vitest run src/components/historian/HistorianView.test.tsx
```

Expected: FAIL — `HistorianView` is still Task 1's placeholder shell, so no mode buttons exist.

- [ ] **Step 21: Write the query form**

Create `11_frontend/src/components/historian/HistorianQueryForm.tsx`:

```tsx
import React from 'react';
import { Clock, RefreshCw } from 'lucide-react';
import { BinaryOperator } from '../../types/uns';
import {
  HistorianMode,
  HistorianQuery,
  MODE_LABELS,
  OPERATOR_MEANING,
  TimePreset,
  resolveHistorianTopic,
} from '../../lib/uns/historian-query';

const MODES: HistorianMode[] = ['topic-time', 'publisher', 'payload-key'];
const PRESETS: TimePreset[] = ['5m', '15m', '1h', '6h', '24h', 'all', 'custom'];
const PRESET_LABELS: Record<TimePreset, string> = {
  '5m': '5m',
  '15m': '15m',
  '1h': '1h',
  '6h': '6h',
  '24h': '24h',
  all: 'All time',
  custom: 'Custom',
};

const fieldClass =
  'w-full rounded border border-[#CBD5E1] bg-[#F8FAFC] px-2.5 py-1.5 font-mono text-[12px] text-[#0F172A] focus:border-amber-500 focus:outline-none dark:border-[#1E293B] dark:bg-[#0B0B0C] dark:text-[#F8FAFC] dark:focus:border-[#FFC107]';
const labelClass = 'text-[11px] font-medium text-[#475569] dark:text-[#94A3B8]';

interface HistorianQueryFormProps {
  query: HistorianQuery;
  onChange: (next: HistorianQuery) => void;
  onRun: () => void;
  loading: boolean;
  error: string | null;
}

export const HistorianQueryForm: React.FC<HistorianQueryFormProps> = ({
  query,
  onChange,
  onRun,
  loading,
  error,
}) => {
  const set = <K extends keyof HistorianQuery>(key: K, value: HistorianQuery[K]) =>
    onChange({ ...query, [key]: value });

  const resolvedTopic = resolveHistorianTopic(query.topic);
  const rewritten = resolvedTopic !== query.topic.trim() && resolvedTopic !== '';

  return (
    <form
      className="space-y-3 rounded-lg border border-[#E2E8F0] bg-white p-4 dark:border-[#1E293B] dark:bg-[#111114]"
      onSubmit={(submit) => {
        submit.preventDefault();
        onRun();
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E2E8F0] pb-3 dark:border-[#1E293B]">
        <div>
          <h1 className="text-[13px] font-semibold text-[#0F172A] dark:text-[#F8FAFC]">Historian</h1>
          <p className="text-[11px] text-[#64748B] dark:text-[#94A3B8]">
            Historic Events recorded from the Unified Namespace.
          </p>
        </div>

        <div
          role="group"
          aria-label="Query the historian"
          className="flex flex-wrap items-center gap-1 rounded border border-[#E2E8F0] bg-[#F1F5F9] p-1 dark:border-[#1E293B] dark:bg-[#0B0B0C]"
        >
          {MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={query.mode === mode}
              onClick={() => set('mode', mode)}
              className={`cursor-pointer rounded px-2.5 py-1 text-[11px] transition-colors ${
                query.mode === mode
                  ? 'bg-amber-500 font-semibold text-[#0B0B0C] dark:bg-[#FFC107]'
                  : 'text-[#64748B] hover:text-[#0F172A] dark:text-[#94A3B8] dark:hover:text-[#F8FAFC]'
              }`}
            >
              {MODE_LABELS[mode]}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-12">
        {query.mode === 'topic-time' && (
          <div className="space-y-1 md:col-span-6">
            <label className={labelClass} htmlFor="historian-topic">
              Topic
            </label>
            <input
              id="historian-topic"
              className={fieldClass}
              value={query.topic}
              onChange={(change) => set('topic', change.target.value)}
              placeholder="CovestroAG/Dormagen/Line1"
            />
          </div>
        )}

        {query.mode === 'publisher' && (
          <div className="space-y-1 md:col-span-6">
            <label className={labelClass} htmlFor="historian-publishers">
              Publishers, comma separated
            </label>
            <input
              id="historian-publishers"
              className={fieldClass}
              value={query.publishers}
              onChange={(change) => set('publishers', change.target.value)}
              placeholder="edge:siemens_s7_1500, edge:beckhoff_twincat"
            />
          </div>
        )}

        {query.mode === 'payload-key' && (
          <>
            <div className="space-y-1 md:col-span-4">
              <label className={labelClass} htmlFor="historian-keys">
                Payload keys, comma separated
              </label>
              <input
                id="historian-keys"
                className={fieldClass}
                value={query.propertyKeys}
                onChange={(change) => set('propertyKeys', change.target.value)}
                placeholder="site, cell_id"
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className={labelClass} htmlFor="historian-operator">
                Match
              </label>
              <select
                id="historian-operator"
                className={fieldClass}
                aria-describedby="historian-operator-meaning"
                value={query.operator}
                onChange={(change) => set('operator', change.target.value as BinaryOperator)}
              >
                <option value="OR">Any key</option>
                <option value="AND">All keys</option>
                <option value="NOT">No key</option>
              </select>
            </div>
          </>
        )}

        <div className="space-y-1 md:col-span-4">
          <label className={`${labelClass} flex items-center gap-1`} id="historian-range-label">
            <Clock className="h-3 w-3 text-amber-600 dark:text-[#FFC107]" />
            <span>Time range</span>
          </label>
          <div
            role="group"
            aria-labelledby="historian-range-label"
            className="flex items-center gap-1 rounded border border-[#E2E8F0] bg-[#F1F5F9] p-0.5 dark:border-[#1E293B] dark:bg-[#0B0B0C]"
          >
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-pressed={query.preset === preset}
                onClick={() => set('preset', preset)}
                className={`flex-1 cursor-pointer rounded py-1 text-[11px] transition-colors ${
                  query.preset === preset
                    ? 'bg-amber-500 font-semibold text-[#0B0B0C] dark:bg-[#FFC107]'
                    : 'text-[#64748B] hover:text-[#0F172A] dark:text-[#94A3B8] dark:hover:text-[#F8FAFC]'
                }`}
              >
                {PRESET_LABELS[preset]}
              </button>
            ))}
          </div>
        </div>

        <div className="md:col-span-2">
          <button
            type="submit"
            disabled={loading}
            className="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded bg-amber-500 py-1.5 text-[12px] font-semibold text-[#0B0B0C] transition-colors hover:bg-amber-600 disabled:opacity-60 dark:bg-[#FFC107] dark:hover:bg-[#FFB300]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>{loading ? 'Querying…' : 'Run query'}</span>
          </button>
        </div>
      </div>

      {query.preset === 'custom' && (
        <div className="flex flex-wrap items-center gap-3 border-t border-[#E2E8F0] pt-2 text-[11px] dark:border-[#1E293B]">
          <div className="flex items-center gap-1.5">
            <label className={labelClass} htmlFor="historian-start">
              From
            </label>
            <input
              id="historian-start"
              type="datetime-local"
              value={query.customStart}
              onChange={(change) => set('customStart', change.target.value)}
              className="rounded border border-[#CBD5E1] bg-[#F8FAFC] px-2 py-0.5 font-mono text-[11px] text-[#0F172A] dark:border-[#1E293B] dark:bg-[#0B0B0C] dark:text-[#F8FAFC]"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <label className={labelClass} htmlFor="historian-end">
              To
            </label>
            <input
              id="historian-end"
              type="datetime-local"
              value={query.customEnd}
              onChange={(change) => set('customEnd', change.target.value)}
              className="rounded border border-[#CBD5E1] bg-[#F8FAFC] px-2 py-0.5 font-mono text-[11px] text-[#0F172A] dark:border-[#1E293B] dark:bg-[#0B0B0C] dark:text-[#F8FAFC]"
            />
          </div>
        </div>
      )}

      <div className="space-y-1 border-t border-[#E2E8F0] pt-2 font-mono text-[11px] text-[#64748B] dark:border-[#1E293B] dark:text-[#94A3B8]">
        {/* The resolver has no LIMIT, so a wide range returns everything it matches. */}
        <p data-testid="historian-no-limit-note">
          This query has no row limit — every matching Historic Event is returned in one
          response. Narrow the time range if a query does not come back.
        </p>
        {query.mode === 'payload-key' && (
          <p id="historian-operator-meaning">
            Matches an event when {OPERATOR_MEANING[query.operator]}, at any depth in the payload.
          </p>
        )}
        {query.mode === 'topic-time' && rewritten && (
          <p data-testid="historian-topic-note">
            Queried as {resolvedTopic} — which also matches {query.topic.trim()} itself.
          </p>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded border border-rose-300 bg-rose-50 px-2.5 py-2 text-[12px] text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
        >
          {error}
        </p>
      )}
    </form>
  );
};
```

- [ ] **Step 22: Write the view, delete `ExploreView`, and point the route at it**

Create `11_frontend/src/components/historian/HistorianView.tsx`:

```tsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { HistoricEvent } from '../../types/uns';
import { unsGraphQLClient } from '../../services/graphql/client';
import { useUNS } from '../../context/UNSContext';
import {
  HistorianQuery,
  defaultQuery,
  parseList,
  resolveHistorianTopic,
  timeBounds,
} from '../../lib/uns/historian-query';
import { HistorianQueryForm } from './HistorianQueryForm';
import { HistorianTable } from './HistorianTable';
import { HistorianTrendChart } from './HistorianTrendChart';

export const HistorianView: React.FC = () => {
  const { historianInitialTopic, selectedNode } = useUNS();

  const [query, setQuery] = useState<HistorianQuery>(() =>
    defaultQuery(historianInitialTopic || selectedNode?.topic || '', Date.now()),
  );
  const [rows, setRows] = useState<HistoricEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState(false);

  const run = useCallback(async () => {
    const { start, end } = timeBounds(query, Date.now());
    setLoading(true);
    setError(null);
    try {
      if (query.mode === 'topic-time') {
        const topic = resolveHistorianTopic(query.topic);
        if (!topic) {
          setError('Enter a topic. A topic with no wildcard is queried as topic/#.');
          setRows([]);
          return;
        }
        setRows(await unsGraphQLClient.getHistoricEvents(topic, start, end));
      } else if (query.mode === 'publisher') {
        const publishers = parseList(query.publishers);
        if (publishers.length === 0) {
          setError('Enter at least one publisher. Publishers are the client ids that wrote the event.');
          setRows([]);
          return;
        }
        setRows(await unsGraphQLClient.getHistoricEventsByPublishers(publishers, undefined, start, end));
      } else {
        const keys = parseList(query.propertyKeys);
        if (keys.length === 0) {
          setError('Enter at least one payload key, for example site or cell_id.');
          setRows([]);
          return;
        }
        setRows(
          await unsGraphQLClient.getHistoricEventsByProperty(keys, query.operator, undefined, start, end),
        );
      }
    } catch (thrown) {
      // All three client methods throw on a transport failure rather than returning a result.
      setError((thrown as Error).message || 'The historian query failed.');
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [query]);

  // A topic arriving from jumpToHistorian is the operator asking for a result, so it runs
  // once. Nothing else auto-runs: the query has no row limit, so it must be deliberate.
  useEffect(() => {
    if (!historianInitialTopic) return;
    setQuery((current) => ({ ...current, mode: 'topic-time', topic: historianInitialTopic }));
    setPendingRun(true);
  }, [historianInitialTopic]);

  useEffect(() => {
    if (!pendingRun) return;
    setPendingRun(false);
    void run();
  }, [pendingRun, run]);

  // The historian SELECT has no ORDER BY, so the order is this view's, not the store's.
  const sortedRows = useMemo(
    () => [...rows].sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp)),
    [rows],
  );

  return (
    <section className="flex-1 space-y-3 overflow-y-auto bg-[#F8FAFC] p-4 text-[12px] text-[#0F172A] dark:bg-[#050505] dark:text-[#F8FAFC]">
      <HistorianQueryForm
        query={query}
        onChange={setQuery}
        onRun={() => setPendingRun(true)}
        loading={loading}
        error={error}
      />

      {sortedRows.length > 0 && (
        <HistorianTrendChart events={sortedRows} selectedTopic={query.topic} />
      )}

      <HistorianTable events={sortedRows} isLoading={loading} />

      <p
        data-testid="historian-order-note"
        className="font-mono text-[11px] text-[#64748B] dark:text-[#94A3B8]"
      >
        Sorted newest first by this screen. The historian returns rows unordered.
      </p>
    </section>
  );
};
```

Delete the old screen and repoint the route:

```bash
cd 11_frontend && git rm src/components/explore/ExploreView.tsx
```

In `11_frontend/src/App.tsx`, replace the import Task 1 left in place:

```tsx
import { HistorianView } from './components/historian/HistorianView';
```

and the route, dropping Task 1's comment about the old screen:

```tsx
          <Route path="/historian" element={<HistorianView />} />
```

`src/components/explore/` is now empty, so git stops tracking it.

- [ ] **Step 23: Run the whole suite and the type check**

```bash
cd 11_frontend && npx vitest run && npx tsc --noEmit
```

Expected: PASS, no TypeScript errors. Two things `tsc` catches if they were missed: any
remaining import of `explore/`, and the dropped `topicTitle` prop on `HistorianTable`.

- [ ] **Step 24: Prove the four untruths are gone**

```bash
cd 11_frontend && grep -rn "Pagination blocked\|restricted by Administrator\|export_csv\|getHistoricEventsBy" src/components || echo "clean"
```

Expected: `clean`. The GraphQL field names now appear only in
`src/services/graphql/client.ts`, and `export_csv` only in `src/types/rbac.ts`, which Task 21
deals with.

- [ ] **Step 25: Commit**

```bash
git add 11_frontend/src/components/historian 11_frontend/src/App.tsx
git add -u 11_frontend/src/components/explore
git commit -m "feat(frontend): rebuild the Historian on what the API supports

The three query modes are named for the question they answer rather than the
GraphQL field they call, and the payload-key mode states which of OR/AND/NOT it
is sending in the resolver's own words. Four untruths go with the old screen:
CSV exported every loaded row while the header counted the filtered ones, a
permission padlock gated rows already on the screen, the footer blamed the
schema for pagination the query does not need, and the form fired an unbounded
historian query on every keystroke. Rows are now sorted newest first by the
view, which says so, because the historian SELECT has no ORDER BY.

Spec section 18 test 13."
```
## Task 19: HEALTH — the transport, the read surface, and a plain list of what a browser cannot see

Spec section 13 fixes this screen's contents exactly: the connection state expanded with
endpoint URLs and two "last seen" timestamps, the embedded `uns-platform-observability`
dashboard together with the Process and OEE switcher, real Asset Model and Alert Rule
counts, and a plain statement of what the console cannot observe. This task builds those
four, and deletes `system/SystemHealthView.tsx` by absorbing it.

**What is already true, verified in the repo before writing this task:**

1. `src/components/system/SystemHealthView.tsx` is 53 lines and reads no `health` at all.
   Commit `0812fc6e` had already rewritten it into a three-dashboard Grafana switcher —
   `platform`, `process`, `oee` — and that switcher is the only thing in the file worth
   keeping. HEALTH takes it over; Task 6 has already moved `GRAFANA_DASHBOARDS` into
   `src/lib/grafana/dashboards.ts` so both files import it from there.
2. `health/HealthView.tsx` exists as the Task 1 placeholder shell. This task replaces its
   body. The route `/health` and the `#/system` → `/health` redirect are already wired.
3. `SystemHealthInfo` carries no timestamps. After the foundation plan it is
   `{ status, graphqlHttp, graphqlWs, lastPingMs, endpointUrl }` — five keys, none naming a
   datastore. Spec section 13 asks for "last successful query" and "last WebSocket event",
   so this task adds them. It also adds the WebSocket URL, because `endpointUrl` names only
   the HTTP half and the client *derives* its WebSocket URL from `window.location` when the
   constructor is given none (`client.ts:82-89`) — so the URL actually in use is not always
   the one in settings, and the health snapshot is the only place that knows.
   That takes the interface to eight keys. The foundation plan's Definition of Done asserts
   five, and that assertion is correct at the end of that plan. The invariant that has to
   survive this task is the other one: **no key names a datastore.**
4. The foundation plan's `client-health.test.ts` asserts the sorted key list literally. Three
   new keys break it, and the fix is to extend the list — that test exists to forbid
   `mqttBroker`, `neo4jTree`, `timescaleHistorian`, `kafkaBroker` and `sparkplugMapper`, not
   to freeze the count. Step 8 updates it.
5. Both counts already have client methods from the foundation plan:
   `getAssetModelSummary(): Promise<AssetModelSummary | null>` and
   `getAlertRuleSummary(): Promise<AlertRuleSummary | null>`. Both resolve to `null` when the
   query fails, and `null` must never render as `0` — a screen that shows "0 Unmodelled
   Topics" because the query failed is the exact class of lie this console is being built to
   remove.
6. There is no GraphQL field that reports per-module health, and this task invents none. A
   `getPlatformHealth` query would be **requires backend**. ADR-0001 records why it does not
   exist: the modules emit to Prometheus, the browser is not Prometheus, and Neo4j Community
   exports no metrics at all.

**One design decision, stated because it is not obvious:** HEALTH reads
`unsGraphQLClient.getHealth()` on a one-second interval rather than consuming
`useUNS().health`. Two reasons. The screen has to re-render as time passes anyway — "4 s
ago" is wrong a second later whether or not anything changed — so it needs a tick
regardless. And the WebSocket stamp is deliberately *not* pushed through `notifyHealth()`:
a `next` frame arrives for every published message, and notifying every health listener on
each one would re-render every consumer of `UNSContext` at broker rate. Stamping a private
field and letting one screen poll it costs nothing; broadcasting it would cost the whole
app.

**Files:**
- Create: `11_frontend/src/lib/health/relative-age.ts`
- Create: `11_frontend/src/components/health/HealthRow.tsx`
- Create: `11_frontend/src/components/health/TransportPanel.tsx`
- Create: `11_frontend/src/components/health/ReadSurfacePanel.tsx`
- Create: `11_frontend/src/components/health/NotObservablePanel.tsx`
- Modify: `11_frontend/src/components/health/HealthView.tsx` — the Task 1 shell, replaced
- Modify: `11_frontend/src/types/uns.ts` — `SystemHealthInfo` gains three keys
- Modify: `11_frontend/src/services/graphql/client.ts` — two stamps and the WebSocket URL
- Modify: `11_frontend/src/services/graphql/client-health.test.ts` — the key list
- Delete: `11_frontend/src/components/system/SystemHealthView.tsx`
- Test: `11_frontend/src/lib/health/relative-age.test.ts`
- Test: `11_frontend/src/components/health/HealthView.test.tsx`

**Interfaces:**
- Consumes: `connectionState(health)` and `ConnectionState` from `src/lib/health/connection-state.ts` (foundation Task 6); `StatusPill` and `PillTone` (Task 5); `EmptyState` (Task 1); `GrafanaEmbed` and `GRAFANA_DASHBOARDS` / `GrafanaDashboardId` from `src/lib/grafana/dashboards.ts` (Task 6); `getAssetModelSummary` / `getAlertRuleSummary` and the `AssetModelSummary` / `AlertRuleSummary` types (foundation Tasks 8 and 9); `useTheme()` from `src/context/ThemeContext.tsx`.
- Produces:
  ```ts
  // lib/health/relative-age.ts
  /** Age of an epoch-millisecond stamp in words. `null` means it has never happened. */
  export function relativeAge(stamp: number | null, now: number): string;

  // types/uns.ts — SystemHealthInfo, extended
  export interface SystemHealthInfo {
    status: ConnectionStatus;
    graphqlHttp: boolean;
    graphqlWs: boolean;
    lastPingMs: number;
    endpointUrl: string;
    wsEndpointUrl: string;
    /** Epoch ms of the last GraphQL HTTP response that carried data. */
    lastQueryAt: number | null;
    /** Epoch ms of the last `next` frame received on the GraphQL WebSocket. */
    lastWsEventAt: number | null;
  }

  // components/health/HealthRow.tsx
  export const HealthRow: React.FC<{
    label: string;
    value: React.ReactNode;
    mono?: boolean;
    title?: string;
    testId?: string;
  }>;

  // components/health/TransportPanel.tsx
  export const TransportPanel: React.FC<{ health: SystemHealthInfo; now: number }>;

  // components/health/ReadSurfacePanel.tsx
  export const ReadSurfacePanel: React.FC<{
    model: AssetModelSummary | null;
    rules: AlertRuleSummary | null;
    loading: boolean;
  }>;

  // components/health/NotObservablePanel.tsx
  export const NotObservablePanel: React.FC;

  // components/health/HealthView.tsx
  export const HealthView: React.FC;
  ```

- [ ] **Step 1: Read the two files this task consumes and replaces**

```bash
cd 11_frontend
cat src/components/system/SystemHealthView.tsx
cat src/components/health/HealthView.tsx
grep -rn "SystemHealthView" src/
grep -n "wsUrl\|lastPingMs\|isLiveBackend\|type === 'next'" src/services/graphql/client.ts
```

Expected: `SystemHealthView` is imported only by `App.tsx` (and that import is removed in
Step 15); `HealthView.tsx` is the placeholder; `client.ts` has a private `wsUrl`, sets
`isLiveBackend = true` inside `if (json.data)`, and handles `msg.type === 'next'` in
`this.ws.onmessage`. If any of those has moved, work from the file rather than from the line
numbers quoted below.

- [ ] **Step 2: Write the failing `relativeAge` test**

Create `11_frontend/src/lib/health/relative-age.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { relativeAge } from './relative-age';

const NOW = 1_756_800_000_000;

describe('relativeAge', () => {
  it('says never when it has not happened', () => {
    expect(relativeAge(null, NOW)).toBe('never');
  });

  it('says just now under two seconds', () => {
    expect(relativeAge(NOW, NOW)).toBe('just now');
    expect(relativeAge(NOW - 1_999, NOW)).toBe('just now');
  });

  it('counts seconds up to a minute', () => {
    expect(relativeAge(NOW - 2_000, NOW)).toBe('2 s ago');
    expect(relativeAge(NOW - 59_000, NOW)).toBe('59 s ago');
  });

  it('counts minutes up to an hour', () => {
    expect(relativeAge(NOW - 60_000, NOW)).toBe('1 min ago');
    expect(relativeAge(NOW - 3_599_000, NOW)).toBe('59 min ago');
  });

  it('counts hours up to a day, then days', () => {
    expect(relativeAge(NOW - 3_600_000, NOW)).toBe('1 h ago');
    expect(relativeAge(NOW - 86_399_000, NOW)).toBe('23 h ago');
    expect(relativeAge(NOW - 86_400_000, NOW)).toBe('1 d ago');
  });

  // A stamp in the future means the clock moved, not that the event is pending.
  it('never reports a negative age', () => {
    expect(relativeAge(NOW + 5_000, NOW)).toBe('just now');
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/lib/health/relative-age.test.ts`
Expected: FAIL — cannot find module `./relative-age`.

- [ ] **Step 4: Implement `relativeAge`**

Create `11_frontend/src/lib/health/relative-age.ts`:

```ts
const SECOND = 1_000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Age of an epoch-millisecond stamp in words, coarsening as it gets older.
 *
 * `now` is a parameter rather than a `Date.now()` call so that this is a pure function and
 * its caller owns the clock. HEALTH ticks once a second and passes the tick's `now`, which
 * is why every age on that screen moves together.
 */
export function relativeAge(stamp: number | null, now: number): string {
  if (stamp === null) {
    return 'never';
  }
  const age = Math.max(0, now - stamp);
  if (age < 2 * SECOND) {
    return 'just now';
  }
  if (age < MINUTE) {
    return `${Math.floor(age / SECOND)} s ago`;
  }
  if (age < HOUR) {
    return `${Math.floor(age / MINUTE)} min ago`;
  }
  if (age < DAY) {
    return `${Math.floor(age / HOUR)} h ago`;
  }
  return `${Math.floor(age / DAY)} d ago`;
}
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd 11_frontend && npx vitest run src/lib/health/relative-age.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 6: Write the failing client-stamp test**

Append to `11_frontend/src/services/graphql/client-health.test.ts`. The existing
`clientWithoutSocket()` helper in that file stubs a silent `WebSocket`; this block needs a
handle on the instance, so it declares its own stub. Keep both — they are testing different
things and a shared stub would have to serve both.

```ts
/** A WebSocket stub that keeps the instance the client built, so a test can drive it. */
class FakeSocket {
  public static last: FakeSocket | null = null
  public onopen: (() => void) | null = null
  public onmessage: ((event: { data: string }) => void) | null = null
  public onerror: (() => void) | null = null
  public onclose: (() => void) | null = null
  public sent: string[] = []
  constructor() {
    FakeSocket.last = this
  }
  send(payload: string) {
    this.sent.push(payload)
  }
  close() {}
}

function clientWithFakeSocket(): UnsGraphQLClient {
  FakeSocket.last = null
  vi.stubGlobal('WebSocket', FakeSocket)
  return new UnsGraphQLClient('/graphql', 'ws://console.test/graphql')
}

describe('observed timestamps', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('has seen nothing before anything has happened', () => {
    const health = clientWithFakeSocket().getHealth()

    expect(health.lastQueryAt).toBeNull()
    expect(health.lastWsEventAt).toBeNull()
  })

  it('reports the WebSocket URL it is actually using', () => {
    expect(clientWithFakeSocket().getHealth().wsEndpointUrl).toBe('ws://console.test/graphql')
  })

  it('stamps the last query when a response carries data', async () => {
    const client = clientWithFakeSocket()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ data: { getUnsNodes: [] } }),
      }),
    )

    const before = Date.now()
    await client.getUnsNodes(['enterprise/facility/area'])
    const after = Date.now()

    const stamp = client.getHealth().lastQueryAt
    expect(stamp).not.toBeNull()
    expect(stamp as number).toBeGreaterThanOrEqual(before)
    expect(stamp as number).toBeLessThanOrEqual(after)
  })

  it('does not stamp a query the endpoint refused', async () => {
    const client = clientWithFakeSocket()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    await client.getUnsNodes(['enterprise/facility/area'])

    expect(client.getHealth().lastQueryAt).toBeNull()
  })

  it('stamps a next frame arriving on the WebSocket', () => {
    const client = clientWithFakeSocket()
    const socket = FakeSocket.last as FakeSocket

    socket.onopen?.()
    const before = Date.now()
    socket.onmessage?.({
      data: JSON.stringify({ type: 'next', id: 'sub-1', payload: { data: {} } }),
    })
    const after = Date.now()

    const stamp = client.getHealth().lastWsEventAt
    expect(stamp).not.toBeNull()
    expect(stamp as number).toBeGreaterThanOrEqual(before)
    expect(stamp as number).toBeLessThanOrEqual(after)
  })

  // connection_ack is protocol handshake, not plant data. An operator asking "is anything
  // still arriving?" is asking about data.
  it('does not treat the protocol handshake as a live update', () => {
    const client = clientWithFakeSocket()
    const socket = FakeSocket.last as FakeSocket

    socket.onopen?.()
    socket.onmessage?.({ data: JSON.stringify({ type: 'connection_ack' }) })

    expect(client.getHealth().graphqlWs).toBe(true)
    expect(client.getHealth().lastWsEventAt).toBeNull()
  })
})
```

Add `afterEach` to the `vitest` import at the top of the file if it is not already there.

- [ ] **Step 7: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-health.test.ts`
Expected: FAIL — `lastQueryAt`, `lastWsEventAt` and `wsEndpointUrl` are all `undefined`, and
the type check on `SystemHealthInfo` rejects them.

- [ ] **Step 8: Extend the key-list assertion in the same file**

The foundation plan's first test in this file asserts the sorted key list. Replace that array
with the eight keys, keeping the comment above it — the point of the assertion is unchanged:

```ts
    expect(Object.keys(health).sort()).toEqual([
      'endpointUrl',
      'graphqlHttp',
      'graphqlWs',
      'lastPingMs',
      'lastQueryAt',
      'lastWsEventAt',
      'status',
      'wsEndpointUrl',
    ])
```

Leave the `does not claim a store is online` test exactly as it is. That is the assertion
that actually constrains this interface, and it still passes unchanged.

- [ ] **Step 9: Extend `SystemHealthInfo`**

In `11_frontend/src/types/uns.ts`, add three keys to the interface the foundation plan
narrowed, and extend its docstring:

```ts
/**
 * What the browser can actually observe about the platform: the GraphQL endpoint, its
 * WebSocket, and when each of them last worked. Nothing else.
 *
 * The five per-store indicators this type used to carry were all derived from one boolean,
 * which is the defect ADR-0001 was written about. Store health is Platform Observability
 * and belongs to Grafana, which is where the modules emit and the browser is not.
 */
export interface SystemHealthInfo {
  status: ConnectionStatus;
  graphqlHttp: boolean;
  graphqlWs: boolean;
  lastPingMs: number;
  endpointUrl: string;
  wsEndpointUrl: string;
  /** Epoch ms of the last GraphQL HTTP response that carried data. Null until one does. */
  lastQueryAt: number | null;
  /** Epoch ms of the last `next` frame on the GraphQL WebSocket. Null until one arrives. */
  lastWsEventAt: number | null;
}
```

- [ ] **Step 10: Stamp the two events in the client**

Three edits in `11_frontend/src/services/graphql/client.ts`.

First, two private fields beside `lastPingMs` (`:74`):

```ts
  private lastQueryAt: number | null = null
  private lastWsEventAt: number | null = null
```

Second, in `this.ws.onmessage`, the `next` branch. The stamp goes outside the
`activeWsSubscriptions` check — a frame that arrives for a subscription this client has since
dropped still proves the WebSocket is delivering. It deliberately does **not** call
`notifyHealth()`; see the note at the head of this task.

```ts
          if (msg.type === 'next') {
            this.lastWsEventAt = Date.now()
            if (msg.id && this.activeWsSubscriptions.has(msg.id)) {
              this.activeWsSubscriptions.get(msg.id)?.(msg.payload?.data)
            }
          }
```

Third, in `executeQuery`, inside the `if (json.data)` branch that already sets
`isLiveBackend`:

```ts
        if (json.data) {
          this.isLiveBackend = true
          this.lastQueryAt = Date.now()
          this.notifyHealth()
          return { data: json.data as T }
        }
```

Then add the three keys to `getHealth()`:

```ts
      lastPingMs: this.lastPingMs || 0,
      endpointUrl: this.httpUrl,
      wsEndpointUrl: this.wsUrl,
      lastQueryAt: this.lastQueryAt,
      lastWsEventAt: this.lastWsEventAt,
```

A GraphQL response whose body is all errors does not stamp `lastQueryAt`, and neither does a
network failure. The stamp means "the read surface answered with data", which is the question
an operator is asking.

- [ ] **Step 11: Run the client tests**

```bash
cd 11_frontend && npx vitest run src/services/graphql/client-health.test.ts
```

Expected: PASS — the existing tests plus the six new ones.

- [ ] **Step 12: Commit the transport plumbing**

```bash
git add 11_frontend/src/types/uns.ts \
  11_frontend/src/services/graphql/client.ts \
  11_frontend/src/services/graphql/client-health.test.ts \
  11_frontend/src/lib/health/relative-age.ts \
  11_frontend/src/lib/health/relative-age.test.ts
git commit -m "feat(frontend): health records when each transport last worked

SystemHealthInfo gains the WebSocket URL the client is actually using and two
nullable stamps: the last GraphQL response that carried data, and the last next
frame on the socket. Both are things the browser genuinely observes, so neither
crosses the line ADR-0001 draws - no key names a datastore.

The WebSocket stamp is not broadcast through notifyHealth(): a next frame
arrives per published message, and re-rendering every UNSContext consumer at
broker rate to move a timestamp would be a bad trade. The HEALTH screen polls."
```

- [ ] **Step 13: Write the failing HEALTH screen test**

Create `11_frontend/src/components/health/HealthView.test.tsx`. The client module is mocked
whole, so this test needs no provider but `ThemeProvider`, and `GrafanaEmbed` is stubbed so
that no iframe is created and the switcher's effect is visible as an attribute.

```tsx
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '../../context/ThemeContext';
import { HealthView } from './HealthView';
import type { SystemHealthInfo } from '../../types/uns';
import { unsGraphQLClient } from '../../services/graphql/client';

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getHealth: vi.fn(),
    getAssetModelSummary: vi.fn(),
    getAlertRuleSummary: vi.fn(),
  },
}));

vi.mock('../common/GrafanaEmbed', () => ({
  GrafanaEmbed: ({ uid, title }: { uid: string; title: string }) => (
    <div data-testid="grafana-embed" data-uid={uid}>
      {title}
    </div>
  ),
}));

const NOW = new Date('2026-09-02T10:00:00.000Z').getTime();

function health(overrides: Partial<SystemHealthInfo> = {}): SystemHealthInfo {
  return {
    status: 'LIVE',
    graphqlHttp: true,
    graphqlWs: true,
    lastPingMs: 41,
    endpointUrl: '/graphql',
    wsEndpointUrl: 'ws://console.test/graphql',
    lastQueryAt: NOW - 5_000,
    lastWsEventAt: NOW - 1_000,
    ...overrides,
  };
}

const mocked = vi.mocked(unsGraphQLClient);

/** Drain the two summary promises without waitFor, which is unreliable on fake timers. */
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function renderHealth(): Promise<void> {
  render(
    <ThemeProvider>
      <HealthView />
    </ThemeProvider>,
  );
  await flush();
}

describe('HealthView', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    mocked.getHealth.mockReturnValue(health());
    mocked.getAssetModelSummary.mockResolvedValue({
      assets: 42,
      metricDefinitions: 118,
      boundTopics: 96,
      unmodelledTopics: 7,
    });
    mocked.getAlertRuleSummary.mockResolvedValue({ total: 12, enabled: 9 });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  it('names both endpoints and when each half last worked', async () => {
    await renderHealth();

    expect(screen.getByTestId('health-status-pill')).toHaveTextContent('Live');
    expect(screen.getByTestId('health-endpoint-http')).toHaveTextContent('/graphql');
    expect(screen.getByTestId('health-endpoint-ws')).toHaveTextContent('ws://console.test/graphql');
    expect(screen.getByTestId('health-last-query')).toHaveTextContent('5 s ago');
    expect(screen.getByTestId('health-last-ws')).toHaveTextContent('just now');
    expect(screen.getByTestId('health-round-trip')).toHaveTextContent('41 ms');
  });

  it('ages the timestamps as the clock moves', async () => {
    await renderHealth();

    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    expect(screen.getByTestId('health-last-query')).toHaveTextContent('8 s ago');
    expect(screen.getByTestId('health-last-ws')).toHaveTextContent('4 s ago');
  });

  it('says never rather than showing a fake time', async () => {
    mocked.getHealth.mockReturnValue(health({ lastQueryAt: null, lastWsEventAt: null }));
    await renderHealth();

    expect(screen.getByTestId('health-last-query')).toHaveTextContent('never');
    expect(screen.getByTestId('health-last-ws')).toHaveTextContent('never');
  });

  it('shows a dash for a round-trip that has never been measured', async () => {
    mocked.getHealth.mockReturnValue(health({ lastPingMs: 0 }));
    await renderHealth();

    expect(screen.getByTestId('health-round-trip')).toHaveTextContent('—');
  });

  it('names which half failed', async () => {
    mocked.getHealth.mockReturnValue(health({ status: 'DEGRADED', graphqlWs: false }));
    await renderHealth();

    expect(screen.getByTestId('health-status-pill')).toHaveTextContent(
      'Degraded — live updates offline',
    );
  });

  it('reports the Asset Model and Alert Rule counts from the read surface', async () => {
    await renderHealth();

    const surface = screen.getByTestId('health-read-surface');
    expect(surface).toHaveTextContent('42');
    expect(surface).toHaveTextContent('118');
    expect(surface).toHaveTextContent('96');
    expect(surface).toHaveTextContent('7');
    expect(surface).toHaveTextContent('12');
    expect(surface).toHaveTextContent('9 enabled');
    expect(surface).toHaveTextContent(
      '7 Unmodelled Topics are being published that the Asset Model does not describe.',
    );
  });

  it('says the Asset Model is fully described when nothing is unmodelled', async () => {
    mocked.getAssetModelSummary.mockResolvedValue({
      assets: 42,
      metricDefinitions: 118,
      boundTopics: 103,
      unmodelledTopics: 0,
    });
    await renderHealth();

    expect(screen.getByTestId('health-read-surface')).toHaveTextContent(
      'Every observed topic is described by the Asset Model.',
    );
  });

  // A failed count must not become a zero. This is the whole reason both client methods
  // return null instead of an empty summary.
  it('does not render a failed count as zero', async () => {
    mocked.getAssetModelSummary.mockResolvedValue(null);
    mocked.getAlertRuleSummary.mockResolvedValue(null);
    await renderHealth();

    const surface = screen.getByTestId('health-read-surface');
    expect(surface).toHaveTextContent('Asset Model counts are unavailable');
    expect(surface).toHaveTextContent('Alert Rule counts are unavailable');
    expect(surface).not.toHaveTextContent('0');
  });

  it('embeds Platform Observability first and switches dashboards', async () => {
    await renderHealth();

    expect(screen.getByTestId('grafana-embed')).toHaveAttribute(
      'data-uid',
      'uns-platform-observability',
    );

    fireEvent.click(screen.getByRole('button', { name: 'OEE' }));
    expect(screen.getByTestId('grafana-embed')).toHaveAttribute('data-uid', 'uns-oee');

    fireEvent.click(screen.getByRole('button', { name: 'Process' }));
    expect(screen.getByTestId('grafana-embed')).toHaveAttribute(
      'data-uid',
      'uns-process-visualization',
    );
  });

  it('says plainly what the browser cannot see', async () => {
    await renderHealth();

    const panel = screen.getByTestId('health-not-observable');
    expect(panel).toHaveTextContent('MQTT broker');
    expect(panel).toHaveTextContent('Graph database');
    expect(panel).toHaveTextContent('Historian');
    expect(panel).toHaveTextContent('Kafka');
    expect(panel).toHaveTextContent(
      'Neo4j Community exports no metrics at all, so no dashboard reports its health either',
    );
  });

  it('stops polling when it unmounts', async () => {
    const { unmount } = render(
      <ThemeProvider>
        <HealthView />
      </ThemeProvider>,
    );
    await flush();
    const callsWhileMounted = mocked.getHealth.mock.calls.length;

    unmount();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(mocked.getHealth.mock.calls.length).toBe(callsWhileMounted);
  });
});
```

Two notes for whoever runs this. `vi.useFakeTimers()` fakes `Date` as well as timers, so
`vi.advanceTimersByTime` moves both the interval and `Date.now()` — which is what makes the
ageing assertions exact. And `waitFor`/`findBy*` are avoided deliberately: their internal
polling and fake timers interact badly, and `flush()` is enough because the only asynchrony
is two already-resolved promises.

- [ ] **Step 14: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/components/health/HealthView.test.tsx`
Expected: FAIL — the placeholder shell renders `Health workspace not built yet`, so every
`getByTestId` misses.

- [ ] **Step 15: Create `HealthRow`**

Create `11_frontend/src/components/health/HealthRow.tsx`. One label-and-value line, so that
the type scale, the truncation and the tabular numerals are decided once for the whole
screen.

```tsx
import React from 'react';

export const HealthRow: React.FC<{
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  title?: string;
  testId?: string;
}> = ({ label, value, mono, title, testId }) => (
  <div
    data-testid={testId}
    className="flex items-baseline justify-between gap-3 py-1 text-[12px]"
  >
    <span className="shrink-0 text-[#475569] dark:text-[#94A3B8]">{label}</span>
    <span
      title={title}
      className={`truncate text-right font-semibold text-[#0F172A] dark:text-[#F8FAFC] ${
        mono ? 'font-mono text-[11px]' : 'tabular-nums'
      }`}
    >
      {value}
    </span>
  </div>
);
```

- [ ] **Step 16: Create `TransportPanel`**

Create `11_frontend/src/components/health/TransportPanel.tsx`. This is spec section 13 item
1: the section 12 chip expanded. It reuses `connectionState` so that the wording here and the
wording in the footer chip can never drift apart.

```tsx
import React from 'react';
import { Activity, Wifi } from 'lucide-react';
import { connectionState } from '../../lib/health/connection-state';
import { relativeAge } from '../../lib/health/relative-age';
import { StatusPill, type PillTone } from '../common/StatusPill';
import type { ConnectionStatus, SystemHealthInfo } from '../../types/uns';
import { HealthRow } from './HealthRow';

const TONE: Record<ConnectionStatus, PillTone> = {
  LIVE: 'good',
  DEGRADED: 'warn',
  DOWN: 'bad',
};

export const TransportPanel: React.FC<{ health: SystemHealthInfo; now: number }> = ({
  health,
  now,
}) => {
  const state = connectionState(health);

  return (
    <section
      data-testid="health-transport"
      className="rounded-md border border-[#E2E8F0] bg-white p-3 dark:border-[#1E293B] dark:bg-[#111114]"
    >
      <header className="mb-2 flex items-center justify-between gap-3 border-b border-[#E2E8F0] pb-2 dark:border-[#1E293B]">
        <h2 className="flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wider text-[#0F172A] dark:text-[#F8FAFC]">
          <Activity className="h-3.5 w-3.5 text-amber-600 dark:text-[#FFC107]" />
          <span>GraphQL read surface</span>
        </h2>
        <span data-testid="health-status-pill">
          <StatusPill label={state.label} tone={TONE[state.status]} title={state.detail} />
        </span>
      </header>

      <p className="mb-2 text-[12px] text-[#475569] dark:text-[#94A3B8]">{state.detail}</p>

      <HealthRow
        label="Queries (HTTP POST)"
        value={health.graphqlHttp ? 'Answering' : 'Not answering'}
      />
      <HealthRow
        label="Live updates (WebSocket)"
        value={
          <span className="inline-flex items-center gap-1.5">
            <Wifi className="h-3 w-3 text-[#64748B]" />
            {health.graphqlWs ? 'Subscribed' : 'Disconnected'}
          </span>
        }
      />
      <HealthRow
        label="Round-trip"
        testId="health-round-trip"
        value={health.lastPingMs === 0 ? '—' : `${health.lastPingMs} ms`}
      />
      <HealthRow
        label="Last query that returned data"
        testId="health-last-query"
        value={relativeAge(health.lastQueryAt, now)}
      />
      <HealthRow
        label="Last live update received"
        testId="health-last-ws"
        value={relativeAge(health.lastWsEventAt, now)}
      />
      <HealthRow
        label="Query endpoint"
        testId="health-endpoint-http"
        mono
        title={health.endpointUrl}
        value={health.endpointUrl}
      />
      <HealthRow
        label="WebSocket endpoint"
        testId="health-endpoint-ws"
        mono
        title={health.wsEndpointUrl}
        value={health.wsEndpointUrl}
      />
    </section>
  );
};
```

`Last live update received` says `never` on a console that is connected but subscribed to
nothing, which is correct and worth seeing: it distinguishes "the socket is up" from "plant
data is arriving", and those are different questions.

- [ ] **Step 17: Create `ReadSurfacePanel`**

Create `11_frontend/src/components/health/ReadSurfacePanel.tsx`. Spec section 13 item 3.
`CONTEXT.md` says counting Unmodelled Topics "is how you tell an incomplete Asset Model from
a complete one", so that count gets a sentence rather than a number in a row. No percentage
and no completeness score is computed here: both would be invented KPIs.

```tsx
import React from 'react';
import { Boxes } from 'lucide-react';
import type { AlertRuleSummary, AssetModelSummary } from '../../services/graphql/types';
import { HealthRow } from './HealthRow';

export const ReadSurfacePanel: React.FC<{
  model: AssetModelSummary | null;
  rules: AlertRuleSummary | null;
  loading: boolean;
}> = ({ model, rules, loading }) => (
  <section
    data-testid="health-read-surface"
    className="rounded-md border border-[#E2E8F0] bg-white p-3 dark:border-[#1E293B] dark:bg-[#111114]"
  >
    <header className="mb-2 flex items-center gap-1.5 border-b border-[#E2E8F0] pb-2 dark:border-[#1E293B]">
      <Boxes className="h-3.5 w-3.5 text-amber-600 dark:text-[#FFC107]" />
      <h2 className="text-[12px] font-bold uppercase tracking-wider text-[#0F172A] dark:text-[#F8FAFC]">
        Asset Model and Alert Rules
      </h2>
    </header>

    {loading ? (
      <p className="text-[12px] text-[#64748B]">Loading counts…</p>
    ) : model === null ? (
      <p className="text-[12px] text-[#B45309] dark:text-[#FFC107]">
        Asset Model counts are unavailable — the query returned no data. This is not a count
        of zero.
      </p>
    ) : (
      <>
        <HealthRow label="Assets" value={model.assets} />
        <HealthRow label="Metric Definitions" value={model.metricDefinitions} />
        <HealthRow label="Bound topics" value={model.boundTopics} />
        <HealthRow label="Unmodelled Topics" value={model.unmodelledTopics} />
        <p className="mt-2 text-[12px] text-[#475569] dark:text-[#94A3B8]">
          {model.unmodelledTopics === 0
            ? 'Every observed topic is described by the Asset Model.'
            : `${model.unmodelledTopics} Unmodelled Topics are being published that the Asset Model does not describe.`}
        </p>
      </>
    )}

    <div className="mt-3 border-t border-[#E2E8F0] pt-2 dark:border-[#1E293B]">
      {loading ? (
        <p className="text-[12px] text-[#64748B]">Loading counts…</p>
      ) : rules === null ? (
        <p className="text-[12px] text-[#B45309] dark:text-[#FFC107]">
          Alert Rule counts are unavailable — the query returned no data. This is not a count
          of zero.
        </p>
      ) : (
        <HealthRow
          label="Alert Rules"
          value={`${rules.total} total, ${rules.enabled} enabled`}
        />
      )}
    </div>
  </section>
);
```

- [ ] **Step 18: Create `NotObservablePanel`**

Create `11_frontend/src/components/health/NotObservablePanel.tsx`. Spec section 13 item 4.
This panel is static text on purpose — it is a statement about the architecture, not a
reading, and there is no query behind it because there is nothing to query.

```tsx
import React from 'react';
import { EyeOff } from 'lucide-react';

const UNREACHABLE = [
  {
    name: 'MQTT broker',
    module: '02_mqtt-cluster',
    note: 'The browser never connects to MQTT. Everything on screen arrived through GraphQL.',
  },
  {
    name: 'Graph database',
    module: '03_uns_graphdb',
    note: 'Neo4j holds the current-state projection. The console reads it only through GraphQL.',
  },
  {
    name: 'Historian',
    module: '04_uns_historian',
    note: 'TimescaleDB holds Historic Events. Queried through GraphQL, never directly.',
  },
  {
    name: 'Kafka',
    module: '06_uns_kafka',
    note: 'A second projection of the same messages, for downstream consumers.',
  },
];

export const NotObservablePanel: React.FC = () => (
  <section
    data-testid="health-not-observable"
    className="rounded-md border border-[#E2E8F0] bg-white p-3 dark:border-[#1E293B] dark:bg-[#111114]"
  >
    <header className="mb-2 flex items-center gap-1.5 border-b border-[#E2E8F0] pb-2 dark:border-[#1E293B]">
      <EyeOff className="h-3.5 w-3.5 text-[#64748B]" />
      <h2 className="text-[12px] font-bold uppercase tracking-wider text-[#0F172A] dark:text-[#F8FAFC]">
        Not visible from this console
      </h2>
    </header>

    <p className="mb-2 text-[12px] text-[#475569] dark:text-[#94A3B8]">
      A browser can only observe the two transports above. The state of these four is in the
      Platform dashboard on the right, where the modules report it themselves.
    </p>

    <ul className="space-y-1.5">
      {UNREACHABLE.map((item) => (
        <li key={item.name} className="text-[12px]">
          <span className="font-semibold text-[#0F172A] dark:text-[#F8FAFC]">{item.name}</span>
          <span className="ml-1.5 font-mono text-[11px] text-[#64748B]">{item.module}</span>
          <span className="block text-[#475569] dark:text-[#94A3B8]">{item.note}</span>
        </li>
      ))}
    </ul>

    <p className="mt-2 border-t border-[#E2E8F0] pt-2 text-[12px] text-[#64748B] dark:border-[#1E293B]">
      Neo4j Community exports no metrics at all, so no dashboard reports its health either.
      The honest answer is that the graph database is only known to be working when a query
      returns data.
    </p>
  </section>
);
```

That last paragraph is ADR-0001 stated to the reader instead of papered over with a green
dot. A per-module health field on the read surface would be **requires backend**, and no such
field exists.

- [ ] **Step 19: Replace `HealthView`**

Replace the whole body of `11_frontend/src/components/health/HealthView.tsx`:

```tsx
import React, { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { GRAFANA_DASHBOARDS, type GrafanaDashboardId } from '../../lib/grafana/dashboards';
import { GrafanaEmbed } from '../common/GrafanaEmbed';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { AlertRuleSummary, AssetModelSummary } from '../../services/graphql/types';
import type { SystemHealthInfo } from '../../types/uns';
import { NotObservablePanel } from './NotObservablePanel';
import { ReadSurfacePanel } from './ReadSurfacePanel';
import { TransportPanel } from './TransportPanel';

/**
 * One second is fast enough for a screen whose smallest unit is "1 s ago", and slow enough
 * that it costs nothing. The tick exists because the ages have to move even when nothing
 * changed, so the whole snapshot is taken here rather than pushed from the client - see the
 * note in the surfaces plan about not broadcasting WebSocket stamps at broker rate.
 */
const TICK_MS = 1000;

interface Snapshot {
  health: SystemHealthInfo;
  now: number;
}

function snapshot(): Snapshot {
  return { health: unsGraphQLClient.getHealth(), now: Date.now() };
}

export const HealthView: React.FC = () => {
  const { isDark } = useTheme();
  const [dashboard, setDashboard] = useState<GrafanaDashboardId>('platform');
  const [{ health, now }, setSnapshot] = useState<Snapshot>(snapshot);
  const [model, setModel] = useState<AssetModelSummary | null>(null);
  const [rules, setRules] = useState<AlertRuleSummary | null>(null);
  const [loadingCounts, setLoadingCounts] = useState(true);

  useEffect(() => {
    const id = window.setInterval(() => setSnapshot(snapshot()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      unsGraphQLClient.getAssetModelSummary(),
      unsGraphQLClient.getAlertRuleSummary(),
    ]).then(([nextModel, nextRules]) => {
      if (cancelled) {
        return;
      }
      setModel(nextModel);
      setRules(nextRules);
      setLoadingCounts(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const active = GRAFANA_DASHBOARDS[dashboard];

  return (
    <section id="health-view" className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-[#E2E8F0] px-4 py-2 dark:border-[#1E293B]">
        <div>
          <h1 className="flex items-center gap-2 text-[13px] font-semibold text-[#0F172A] dark:text-[#E2E8F0]">
            <Activity className="h-4 w-4 text-amber-600 dark:text-[#FFC107]" />
            <span>Health</span>
          </h1>
          <p className="mt-0.5 text-[11px] text-[#64748B]">
            What this browser observes, and what only Platform Observability can see.
          </p>
        </div>

        <div
          data-testid="health-dashboard-switcher"
          className="flex items-center gap-1 rounded border border-[#E2E8F0] bg-[#F8FAFC] p-0.5 dark:border-[#1E293B] dark:bg-[#111114]"
        >
          {(Object.keys(GRAFANA_DASHBOARDS) as GrafanaDashboardId[]).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setDashboard(id)}
              aria-pressed={dashboard === id}
              className={`rounded px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                dashboard === id
                  ? 'bg-amber-500 text-[#0F172A] dark:bg-[#FFC107]'
                  : 'text-[#475569] hover:text-[#0F172A] dark:text-[#94A3B8] dark:hover:text-[#F8FAFC]'
              }`}
            >
              {GRAFANA_DASHBOARDS[id].label}
            </button>
          ))}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="w-[400px] shrink-0 space-y-3 overflow-y-auto border-r border-[#E2E8F0] p-3 dark:border-[#1E293B]">
          <TransportPanel health={health} now={now} />
          <ReadSurfacePanel model={model} rules={rules} loading={loadingCounts} />
          <NotObservablePanel />
        </div>

        <div className="min-h-0 flex-1">
          <GrafanaEmbed
            uid={active.uid}
            theme={isDark ? 'dark' : 'light'}
            title={`${active.label} dashboard`}
          />
        </div>
      </div>
    </section>
  );
};
```

The left column scrolls and the shell does not, which is the layout rule for every surface in
this console.

- [ ] **Step 20: Run the screen test**

Run: `cd 11_frontend && npx vitest run src/components/health/HealthView.test.tsx`
Expected: PASS, 11 tests.

- [ ] **Step 21: Delete `SystemHealthView` and drop its route import**

`HealthView` now does everything that file did and more, and `/system` already redirects to
`/health`.

```bash
cd 11_frontend
git rm src/components/system/SystemHealthView.tsx
rmdir src/components/system 2>/dev/null || true
grep -rn "SystemHealthView" src/ || echo "no references remain"
```

If `grep` still finds the import in `src/App.tsx`, remove that import line. Task 1 replaced
the `/system` route with a `<Navigate to="/health" replace />`, so nothing else refers to it.
Leave `src/components/system/` in place if any other file still lives there.

- [ ] **Step 22: Run the whole suite and the type check**

```bash
cd 11_frontend && npx tsc --noEmit && npx vitest run
```

Expected: no type errors and a green suite. `client-health.test.ts` in particular must pass —
it is the test that guards the shape of `SystemHealthInfo`, and Step 8 changed it.

- [ ] **Step 23: Commit**

```bash
git add 11_frontend/src/components/health/ \
  11_frontend/src/App.tsx
git rm --cached --ignore-unmatch 11_frontend/src/components/system/SystemHealthView.tsx
git commit -m "feat(frontend): HEALTH says what the browser sees and what it cannot

Four panels, all of them true. The two transports with the URLs in use and when
each last worked. Asset Model and Alert Rule counts from the read surface, where
a failed query reads 'unavailable' rather than zero. The Platform Observability
dashboard, with the Process and OEE switcher absorbed from SystemHealthView,
which this commit deletes. And a named list of the four things a browser cannot
reach - broker, graph database, historian, Kafka - including the fact that Neo4j
Community exports no metrics at all, so nothing reports its health.

Spec section 13. ADR-0001 stated to the operator instead of drawn as a green
dot."
```

---
## Task 20: ALARMS — delete the fictional plant, and stop silence from meaning "normal"

Spec section 11 lists two rows for `AlarmContext.tsx`: `INITIAL_RULES` deleted, and
`restoreDefaults()` removed. Both are here. So are three things found while reading the file,
each of which is the same untruth one layer down.

**What is in the file, verified line by line:**

1. `INITIAL_RULES` (`:42`–`:212`) is three rules on
   `CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature`,
   `CovestroAG/Krefeld_Uerdingen/Polycarbonates/Extrusion_Line_02/pressure` and
   `CovestroAG/Leverkusen/MDI/Distillation_Column/vibration`, complete with
   `triggerCount: 8` and webhooks pointing at `ops-webhook.covestro.internal`. Neither
   `Polyurethane` nor `Reactor_01` appears anywhere in `conf/` or `99_simulator/`.
2. **These rules escape into shared Postgres on their own.** `refreshRules` (`:409`–`:433`)
   asks the platform for rules; if the platform holds *none*, it POSTs
   `rulesRef.current` through `saveAlertRules`. On a fresh browser `rulesRef.current` is
   `INITIAL_RULES`. So the first console ever opened against an empty platform writes three
   fabricated rules into the database every other console then reads. Deleting the constant
   is what actually closes this, and the hand-over path itself is worth keeping — it is the
   migration route for rules authored before the server could store them. It just has to
   stop firing when there is nothing to hand over.
3. `INITIAL_ACTIVE_ALARMS` (`:213`–`:262`) and `INITIAL_ALARM_AUDIT` (`:264`–`:301`) are the
   same fabrication for the other two collections: an `ACTIVE_UNACK` alarm reading
   `88.4 °C` on the reactor that does not exist, and an audit trail crediting acknowledgements
   to named people. They go with the rules, and not only for honesty — their `ruleId`s point
   at `rule-temp-01` and `rule-press-02`, so leaving them would leave active alarms belonging
   to rules that no longer exist anywhere.
4. `restoreDefaultRules` (`:1019`–`:1054`) deletes every rule the site has authored, POSTs
   `INITIAL_RULES` back, and is **called by nothing** — `grep -rn "restoreDefaultRules" src/`
   finds only its own declaration, type member and provider value. It is dead code whose only
   capability is rewriting plant configuration for everybody.
5. The topic matcher (`:648`–`:655`) is inline and wrong in two ways: it cannot handle a
   filter containing both `+` and `#`, and it builds `new RegExp` from the filter without
   escaping, so a rule on a topic containing `.` matches topics that merely have some other
   character in that position. Task 14 already extracted `topicMatchesFilter` for the PLANT
   tab. Two copies of a subtly wrong matcher is how an alarm silently stops firing.
6. **The active-alarm empty state states a fact about the plant that it cannot know.**
   `AlarmManagementView.tsx:392`–`:400` reads `No Active Incidents` /
   `All ISA-95 node metrics and edge streams are operating within configured tolerances`.
   With zero rules configured — which, after this task, is what a fresh install has —
   nothing is being evaluated at all, and an empty list means nobody is watching rather than
   nothing is wrong. This is the most dangerous sentence in the console, because it is
   reassurance produced by absence.
7. **There is no empty state for zero rules.** `rules.map(...)` at `:635` renders a table with
   headers and no rows, which reads like a loading state that never finishes.
8. `AlarmAuditLog.tsx:38`–`:60` hand-rolls CSV: it quotes every field whether or not it needs
   quoting, joins rows with `\n`, and never calls `URL.revokeObjectURL`, so every export
   leaks a blob for the life of the tab. Task 18 already produced `toCsv` and `downloadCsv`.
   Two CSV writers in one console is one too many.

Nothing here changes where evaluation happens. ADR-0005 accepted browser-side evaluation;
this task surfaces it with `BrowserEvaluationNotice` from Task 14 instead of concealing it.

**Files:**
- Modify: `11_frontend/src/context/AlarmContext.tsx:42`–`:302`, `:409`–`:433`, `:648`–`:655`, `:334`, `:1019`–`:1054`, `:1083`
- Modify: `11_frontend/src/components/alarms/AlarmManagementView.tsx:392`–`:400`, `:567`–`:635`
- Modify: `11_frontend/src/components/alarms/AlarmAuditLog.tsx:38`–`:60`
- Test: `11_frontend/src/context/AlarmContext.test.tsx`
- Test: `11_frontend/src/components/alarms/AlarmManagementView.test.tsx`

**Interfaces:**
- Consumes: `topicMatchesFilter` from `src/lib/uns/topic-match.ts` and `BrowserEvaluationNotice` from `src/components/alarms/BrowserEvaluationNotice.tsx` (both Task 14); `toCsv`, `downloadCsv` and `CsvColumn` from `src/lib/csv/to-csv.ts` (Task 18); `EmptyState` (Task 1).
- Produces: `AlarmContextType` **without** `restoreDefaultRules`. Everything else on the context keeps its current name and signature. No new export.

- [ ] **Step 1: Confirm what is being deleted and that nothing calls it**

```bash
cd 11_frontend
grep -rn "restoreDefaultRules" src/
grep -n "INITIAL_RULES\|INITIAL_ACTIVE_ALARMS\|INITIAL_ALARM_AUDIT" src/context/AlarmContext.tsx
grep -rn "Polyurethane\|Reactor_01" src/ ../conf ../99_simulator | grep -v node_modules
```

Expected: `restoreDefaultRules` appears only in `AlarmContext.tsx` (three times); the three
constants appear only in `AlarmContext.tsx`; `Polyurethane` and `Reactor_01` appear only in
`AlarmContext.tsx` and nowhere in `conf/` or `99_simulator/`. If any view does call
`restoreDefaultRules`, stop and remove that call site in this task as well.

- [ ] **Step 2: Write the failing context test**

Create `11_frontend/src/context/AlarmContext.test.tsx`. `AlarmProvider` depends on two other
contexts and on the client, so all three are mocked at the module boundary — that is the same
rule the rest of this suite follows, and it keeps the test about alarm behaviour.

```tsx
import { act, render } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AlarmProvider, useAlarms } from './AlarmContext';
import type { AlertRule } from '../types/alarm';
import type { MqttMessage } from '../types/uns';
import { unsGraphQLClient } from '../services/graphql/client';

let feed: MqttMessage[] = [];

vi.mock('./UNSContext', () => ({
  useUNS: () => ({ mqttFeed: feed }),
}));

vi.mock('./AuthContext', () => ({
  useAuth: () => ({
    currentUser: { id: 'u-test', name: 'Test Operator', role: 'operator' },
  }),
}));

vi.mock('../services/graphql/client', () => ({
  unsGraphQLClient: {
    getAlertRules: vi.fn(),
    saveAlertRules: vi.fn(),
    saveAlertRule: vi.fn(),
    deleteAlertRule: vi.fn(),
    recordAlertRuleEvaluation: vi.fn(),
  },
}));

const mocked = vi.mocked(unsGraphQLClient);

/** A rule that breaches on `temp > 80`, with the chime off so jsdom needs no audio. */
function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r-1',
    name: 'Line 1 temperature high',
    description: '',
    enabled: true,
    severity: 'HIGH',
    category: 'TEMPERATURE',
    topic: 'CovestroAG/+/Production/#',
    metricField: 'temp',
    condition: 'GREATER_THAN',
    thresholdValue: 80,
    unit: '°C',
    delaySeconds: 0,
    targetRoles: ['operator'],
    autoResolveOnNormal: false,
    actions: { inAppNotification: true, audioChime: false },
    triggerCount: 0,
    createdAt: '2026-09-01T00:00:00.000Z',
    updatedAt: '2026-09-01T00:00:00.000Z',
    ...overrides,
  } as AlertRule;
}

function message(topic: string, payload: Record<string, unknown>): MqttMessage {
  return {
    id: `m-${topic}`,
    topic,
    payload,
    timestamp: '2026-09-02T10:00:00.000Z',
  };
}

type Ctx = ReturnType<typeof useAlarms>;
let ctx: Ctx | null = null;

const Probe: React.FC = () => {
  ctx = useAlarms();
  return null;
};

async function mount(): Promise<void> {
  render(
    <AlarmProvider>
      <Probe />
    </AlarmProvider>,
  );
  // Drain refreshRules and, when rules arrive, the evaluation effect they retrigger.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AlarmProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    feed = [];
    ctx = null;
    mocked.getAlertRules.mockResolvedValue([]);
    mocked.saveAlertRules.mockResolvedValue([]);
    mocked.recordAlertRuleEvaluation.mockResolvedValue(undefined as never);
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('starts with nothing, on a platform that holds nothing', async () => {
    await mount();

    expect(ctx?.rules).toEqual([]);
    expect(ctx?.activeAlarms).toEqual([]);
    expect(ctx?.auditLog).toEqual([]);
  });

  // The defect this task closes: a fresh browser used to POST three invented rules into
  // shared Postgres the first time it saw an empty platform.
  it('does not write anything to the platform when it has no rules of its own', async () => {
    await mount();

    expect(mocked.saveAlertRules).not.toHaveBeenCalled();
    expect(ctx?.rulesOrigin).toBe('SERVER');
    expect(ctx?.rulesError).toBeNull();
  });

  it('still hands over rules this browser cached before the server could store them', async () => {
    const cached = rule({ id: 'r-cached', name: 'Authored here first' });
    localStorage.setItem('uns_alert_rules_v1', JSON.stringify([cached]));
    mocked.saveAlertRules.mockResolvedValue([cached]);

    await mount();

    expect(mocked.saveAlertRules).toHaveBeenCalledWith([cached]);
    expect(ctx?.rules).toEqual([cached]);
    expect(ctx?.rulesOrigin).toBe('SERVER');
  });

  it('raises an alarm when a filter with both + and # covers the topic', async () => {
    mocked.getAlertRules.mockResolvedValue([rule()]);
    feed = [message('CovestroAG/Dormagen/Production/Line1/Cell1', { temp: 91 })];

    await mount();

    expect(ctx?.activeAlarms).toHaveLength(1);
    expect(ctx?.activeAlarms[0].topic).toBe('CovestroAG/Dormagen/Production/Line1/Cell1');
    expect(ctx?.activeAlarms[0].status).toBe('ACTIVE_UNACK');
  });

  it('does not raise an alarm for a topic the filter does not cover', async () => {
    mocked.getAlertRules.mockResolvedValue([rule()]);
    feed = [message('CovestroAG/Dormagen/Packaging/Line1/Cell1', { temp: 91 })];

    await mount();

    expect(ctx?.activeAlarms).toEqual([]);
  });

  // The old inline matcher built a RegExp from the filter without escaping, so a dot in a
  // topic matched any character.
  it('treats a dot in a topic as a dot', async () => {
    mocked.getAlertRules.mockResolvedValue([rule({ topic: 'Plant/A.B/temp' })]);
    feed = [message('Plant/AxB/temp', { temp: 91 })];

    await mount();

    expect(ctx?.activeAlarms).toEqual([]);
  });

  it('has no way to restore fictional defaults', async () => {
    await mount();

    expect((ctx as unknown as Record<string, unknown>).restoreDefaultRules).toBeUndefined();
  });
});
```

The cached-rules test writes `uns_alert_rules_v1`, which is `STORAGE_KEYS.RULES` at
`AlarmContext.tsx:27`. `STORAGE_KEYS` is not exported, so the literal is deliberate — check it
still matches before running.

- [ ] **Step 3: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/context/AlarmContext.test.tsx`
Expected: FAIL — `rules` is the three seeded rules, `activeAlarms` has two, `auditLog` has
three, `saveAlertRules` was called with `INITIAL_RULES`, the dot test raises an alarm, and
`restoreDefaultRules` is a function.

- [ ] **Step 4: Delete the three fabricated collections**

Delete `11_frontend/src/context/AlarmContext.tsx:42`–`:302` — `INITIAL_RULES`,
`INITIAL_ACTIVE_ALARMS` and `INITIAL_ALARM_AUDIT`, from `const INITIAL_RULES` through the
blank line before `interface AlarmContextType`. Then fix the three initialisers that referred
to them, so each collection starts empty:

```tsx
  // The cached rules render first so the alarm list is never briefly empty; the
  // server's answer replaces them as soon as it arrives.
  const [rules, setRules] = useState<AlertRule[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.RULES);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    // No seeded rules. A rule names real equipment or it does not exist.
    return [];
  });
```

```tsx
    return [];
  });
```

for `activeAlarms` and `auditLog` in place of `return INITIAL_ACTIVE_ALARMS;` and
`return INITIAL_ALARM_AUDIT;`. Then remove `AlarmAuditEntry` or `ActiveAlarm` from the type
import at the top only if `tsc` reports them unused — both are still used by the state
generics, so most likely nothing changes there.

- [ ] **Step 5: Stop the hand-over from firing when there is nothing to hand over**

In `refreshRules`, replace the final block (`:424`–`:432`):

```tsx
    // Nothing to hand over. An empty platform plus an empty browser is not a migration,
    // and POSTing an empty list would be a write nobody asked for.
    if (rulesRef.current.length === 0) {
      setRulesOrigin('SERVER');
      setRulesError(null);
      return;
    }

    try {
      const imported = await unsGraphQLClient.saveAlertRules(rulesRef.current);
      setRules(imported);
      setRulesOrigin('SERVER');
      setRulesError(null);
    } catch (error) {
      setRulesOrigin('BROWSER');
      setRulesError(error instanceof Error ? error.message : 'Alert Rules could not be stored');
    }
```

`SERVER` is the honest origin in the new branch: the platform answered, and what it holds is
nothing. `BROWSER` would say the rules on screen are local, and there are none.

- [ ] **Step 6: Use the tested matcher**

Add the import:

```tsx
import { topicMatchesFilter } from '../lib/uns/topic-match';
```

and replace `:648`–`:655`:

```tsx
      // Check topic matching
      const topicMatches = rule.topic === '*' || topicMatchesFilter(rule.topic, latestMessage.topic);
```

`topicMatchesFilter` already treats `*` as everything, so the first clause is redundant —
keep it anyway, because a rule stored with `*` is matched before the function is entered and
that is one less thing to reason about at 3 a.m.

- [ ] **Step 7: Delete `restoreDefaultRules`**

Three deletions:

- `:334` — the `restoreDefaultRules: () => void;` member of `AlarmContextType`.
- `:1019`–`:1054` — the docstring, the `useCallback`, everything through its closing `}, []);`.
- `:1083` — the `restoreDefaultRules,` line in the provider value.

Nothing else refers to it. If `deleteAlertRule` or `rulesRef` becomes unused as a result,
`tsc --noEmit` will say so in Step 12 — both are used elsewhere, so they should not.

- [ ] **Step 8: Run the context test**

Run: `cd 11_frontend && npx vitest run src/context/AlarmContext.test.tsx`
Expected: PASS, 7 tests.

- [ ] **Step 9: Write the failing view test**

Create `11_frontend/src/components/alarms/AlarmManagementView.test.tsx`. `useAlarms` is
mocked rather than wrapped in a provider, because what is under test is what this screen says
about a given state — the provider's behaviour is Step 2's test.

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AlarmManagementView } from './AlarmManagementView';
import type { AlertRule } from '../../types/alarm';

const alarms = {
  rules: [] as AlertRule[],
  activeAlarms: [],
  auditLog: [],
  isMuted: false,
  rulesOrigin: 'SERVER' as const,
  rulesError: null,
  myRoleAlarms: [],
  myUnacknowledgedCount: 0,
  totalUnacknowledgedCount: 0,
  criticalAlarmsCount: 0,
  refreshRules: vi.fn(),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  deleteRule: vi.fn(),
  toggleRuleEnabled: vi.fn(),
  testTriggerRule: vi.fn(),
  acknowledgeAlarm: vi.fn(),
  resolveAlarm: vi.fn(),
  bulkAcknowledgeAll: vi.fn(),
  toggleAudioMute: vi.fn(),
  playAlarmChime: vi.fn(),
  clearResolvedAlarms: vi.fn(),
};

vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => alarms,
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    currentUser: { id: 'u-test', name: 'Test Operator', role: 'operator' },
    isAdmin: false,
  }),
}));

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({ jumpToHistorian: vi.fn(), jumpToTopicInTree: vi.fn() }),
}));

function enabledRule(): AlertRule {
  return {
    id: 'r-1',
    name: 'Line 1 temperature high',
    description: '',
    enabled: true,
    severity: 'HIGH',
    category: 'TEMPERATURE',
    topic: 'CovestroAG/Dormagen/Production/Line1/#',
    metricField: 'temp',
    condition: 'GREATER_THAN',
    thresholdValue: 80,
    unit: '°C',
    delaySeconds: 0,
    targetRoles: ['operator'],
    autoResolveOnNormal: false,
    actions: { inAppNotification: true, audioChime: false },
    triggerCount: 0,
    createdAt: '2026-09-01T00:00:00.000Z',
    updatedAt: '2026-09-01T00:00:00.000Z',
  } as AlertRule;
}

describe('AlarmManagementView', () => {
  it('does not call an unwatched plant normal', () => {
    alarms.rules = [];
    render(<AlarmManagementView />);

    const empty = screen.getByTestId('alarms-empty');
    expect(empty).toHaveTextContent('No Alert Rules are configured');
    expect(empty).toHaveTextContent('nothing is being evaluated');
    expect(empty).not.toHaveTextContent('within configured tolerances');
    expect(empty).not.toHaveTextContent('normal parameters');
  });

  it('says so when every rule is switched off', () => {
    alarms.rules = [{ ...enabledRule(), enabled: false }];
    render(<AlarmManagementView />);

    expect(screen.getByTestId('alarms-empty')).toHaveTextContent(
      'All 1 Alert Rules are disabled',
    );
  });

  it('reports a quiet plant only when something is watching it', () => {
    alarms.rules = [enabledRule()];
    render(<AlarmManagementView />);

    const empty = screen.getByTestId('alarms-empty');
    expect(empty).toHaveTextContent('No enabled Alert Rule is currently breached');
    expect(empty).toHaveTextContent('while this console is open');
  });
});
```

The three assertions on the same `data-testid` are the point: one empty list, three different
truths, and the current code tells the third one in all three cases.

- [ ] **Step 10: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/components/alarms/AlarmManagementView.test.tsx`
Expected: FAIL — no element has `data-testid="alarms-empty"`, and the text is the
`configured tolerances` sentence.

- [ ] **Step 11: Rewrite the two empty states and add the notice**

First, `AlarmManagementView.tsx:392`–`:400`. Above the `return` in the component, derive the
one fact the empty state turns on:

```tsx
  const enabledRuleCount = rules.filter((r) => r.enabled).length;
```

Then replace the empty branch's heading and paragraph:

```tsx
              <div
                data-testid="alarms-empty"
                className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-12 text-center text-[#64748B] space-y-3"
              >
                {rules.length === 0 ? (
                  <AlertTriangle className="w-12 h-12 text-amber-500 dark:text-[#FFC107] mx-auto opacity-70" />
                ) : (
                  <CheckCircle2 className="w-12 h-12 text-emerald-500 dark:text-emerald-400 mx-auto opacity-70" />
                )}
                <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-sm text-balance">
                  No active alarms
                </h3>
                <p className="text-[12px] text-[#64748B] dark:text-[#94A3B8] max-w-md mx-auto text-pretty">
                  {rules.length === 0
                    ? 'No Alert Rules are configured, so nothing is being evaluated. An empty list here says nobody is watching, not that the plant is running well.'
                    : enabledRuleCount === 0
                      ? `All ${rules.length} Alert Rules are disabled, so nothing is being evaluated.`
                      : roleFilter === 'my_role'
                        ? `No enabled Alert Rule routed to role '${currentUser.role}' is currently breached, while this console is open.`
                        : `No enabled Alert Rule is currently breached, while this console is open.`}
                </p>
```

Leave the button that follows the paragraph as it is.

The `while this console is open` clause is not padding. ADR-0005 means an alarm that would
have fired overnight did not, and a screen that says "no active alarms" without that clause
is claiming a quiet night it never observed.

Second, the rules tab. Add the imports:

```tsx
import { BrowserEvaluationNotice } from './BrowserEvaluationNotice';
import { EmptyState } from '../common/EmptyState';
```

Put the notice under the rules-header paragraph at `:573`:

```tsx
                <p className="text-[11px] text-[#64748B] dark:text-[#94A3B8] text-pretty">
                  Define telemetry thresholds, evaluation conditions, and the predefined roles that receive alerts.
                </p>
                <BrowserEvaluationNotice className="mt-1" />
```

And give the table an empty state — replace the wrapper `div` that contains it (`:620` to the
closing of the table block) with a conditional:

```tsx
            {rules.length === 0 ? (
              <EmptyState
                title="No Alert Rules are configured"
                detail="Add a rule to watch a topic's payload against a threshold. Rules are stored on the platform and shared with every console at this site."
              />
            ) : (
              <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl overflow-hidden">
                {/* the existing overflow-x-auto table, unchanged */}
              </div>
            )}
```

Keep the table markup exactly as it is inside the `else` branch — this step adds a wrapper
and changes nothing about the rows.

- [ ] **Step 12: Run both tests and the type check**

```bash
cd 11_frontend && npx tsc --noEmit \
  && npx vitest run src/context/AlarmContext.test.tsx src/components/alarms/AlarmManagementView.test.tsx
```

Expected: no type errors, 10 tests passing.

- [ ] **Step 13: Commit the honesty changes**

```bash
git add 11_frontend/src/context/AlarmContext.tsx \
  11_frontend/src/context/AlarmContext.test.tsx \
  11_frontend/src/components/alarms/AlarmManagementView.tsx \
  11_frontend/src/components/alarms/AlarmManagementView.test.tsx
git commit -m "fix(frontend): ALARMS stops inventing a plant and stops calling silence normal

Three seeded collections deleted: rules on Polyurethane/Reactor_01, an active
alarm reading 88.4 C on that reactor, and an audit trail crediting named people
with acknowledging it. None of that equipment exists in conf/ or 99_simulator/.

They were not only cosmetic. refreshRules POSTs this browser's rules when the
platform holds none, so the first console opened against an empty database wrote
all three fabricated rules into shared Postgres for every other console to read.
That branch now returns early when there is nothing to hand over.

restoreDefaultRules is gone. It deleted every authored rule and POSTed the
fictional ones back, and nothing ever called it.

The topic matcher is now the tested topicMatchesFilter, which handles a filter
with both + and # and escapes regex metacharacters - the inline version matched
Plant/AxB against a rule on Plant/A.B.

And the empty alarm list no longer reads 'operating within configured
tolerances'. With no rules configured nothing is being evaluated, and the screen
now says which of the three situations it is in. ADR-0005's browser-side
evaluation is stated rather than concealed."
```

- [ ] **Step 14: Write the failing audit-export test**

Append to `11_frontend/src/components/alarms/AlarmManagementView.test.tsx` — the audit log is
reached through this screen, and mocking `downloadCsv` keeps jsdom's missing
`URL.createObjectURL` out of it while the real `toCsv` still runs.

```tsx
import userEvent from '@testing-library/user-event';
import { downloadCsv } from '../../lib/csv/to-csv';
import { AlarmAuditLog } from './AlarmAuditLog';

vi.mock('../../lib/csv/to-csv', async () => {
  const actual = await vi.importActual<typeof import('../../lib/csv/to-csv')>(
    '../../lib/csv/to-csv',
  );
  return { ...actual, downloadCsv: vi.fn() };
});

describe('AlarmAuditLog export', () => {
  it('exports the rows on screen through the shared CSV writer', async () => {
    alarms.auditLog = [
      {
        id: 'aud-1',
        timestamp: '2026-09-02T09:58:00.000Z',
        alarmId: 'alm-1',
        ruleName: 'Line 1 temperature high',
        topic: 'CovestroAG/Dormagen/Production/Line1/Cell1',
        severity: 'HIGH',
        action: 'TRIGGERED',
        actorName: 'UNS Ingestion Engine',
        actorRole: 'admin',
        details: 'temp (91 °C) > 80 °C, "high" band',
      },
    ];
    render(<AlarmAuditLog />);

    await userEvent.click(screen.getByRole('button', { name: /export/i }));

    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [filename, csv] = vi.mocked(downloadCsv).mock.calls[0];
    expect(filename).toMatch(/^uns-alarm-audit-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv.split('\r\n')[0]).toBe(
      'Timestamp,Action,Severity,Rule Name,Topic,Actor Name,Actor Role,Details',
    );
    // The details field contains a comma and a quote, so it is the one field quoted.
    expect(csv).toContain('"temp (91 °C) > 80 °C, ""high"" band"');
    expect(csv).toContain('UNS Ingestion Engine');
  });
});
```

`alarms.auditLog` is typed `[]` in the harness above; widen it to
`auditLog: [] as AlarmAuditEntry[]` and import `AlarmAuditEntry` from `../../types/alarm` so
this assignment type-checks.

- [ ] **Step 15: Run it to verify it fails**

Run: `cd 11_frontend && npx vitest run src/components/alarms/AlarmManagementView.test.tsx`
Expected: FAIL — `downloadCsv` is never called; the component builds its own blob.

- [ ] **Step 16: Route the audit export through `toCsv`**

Replace `AlarmAuditLog.tsx:38`–`:60` with:

```tsx
  const exportCSV = () => {
    const columns: CsvColumn<AlarmAuditEntry>[] = [
      { header: 'Timestamp', value: (e) => e.timestamp },
      { header: 'Action', value: (e) => e.action },
      { header: 'Severity', value: (e) => e.severity },
      { header: 'Rule Name', value: (e) => e.ruleName },
      { header: 'Topic', value: (e) => e.topic },
      { header: 'Actor Name', value: (e) => e.actorName },
      { header: 'Actor Role', value: (e) => e.actorRole },
      { header: 'Details', value: (e) => e.details },
    ];
    const today = new Date().toISOString().slice(0, 10);
    downloadCsv(`uns-alarm-audit-${today}.csv`, toCsv(columns, filteredLogs));
  };
```

with the imports:

```tsx
import { downloadCsv, toCsv, type CsvColumn } from '../../lib/csv/to-csv';
import type { AlarmAuditEntry } from '../../types/alarm';
```

`filteredLogs`, not `auditLog` — the button exports what the filters left on screen, which is
the same rule Task 18 settled for the historian. `toCsv` quotes only fields that need it and
joins with `\r\n`; `downloadCsv` revokes the object URL, which the hand-rolled version never
did.

Add an empty row to the table body while it is open, so a filtered-to-nothing audit trail does
not look like a stuck load. Directly after `{filteredLogs.map(...)}` inside `<tbody>`:

```tsx
              {filteredLogs.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 px-3 text-center text-[12px] text-[#64748B]">
                    No audit entries match these filters. The trail is browser-local and starts
                    empty in a new browser.
                  </td>
                </tr>
              )}
```

Check the `<thead>` row before committing to `colSpan={6}` and use the real column count.

- [ ] **Step 17: Run everything and commit**

```bash
cd 11_frontend && npx tsc --noEmit && npx vitest run
```

Expected: no type errors, green suite.

```bash
git add 11_frontend/src/components/alarms/AlarmAuditLog.tsx \
  11_frontend/src/components/alarms/AlarmManagementView.test.tsx
git commit -m "refactor(frontend): the alarm audit export uses the shared CSV writer

One CSV writer, not two. The hand-rolled version quoted every field whether it
needed it or not, joined rows with a bare newline, and never revoked its object
URL - one leaked blob per export for the life of the tab. It also exported
auditLog while the table showed filteredLogs; the button now exports the rows on
screen, the same rule the historian follows.

An empty trail says it is browser-local and starts empty, instead of showing a
table with headers and no rows."
```

---

---

## Task 21: USERS — a read-only list of browser-local accounts, and an audit trail that audits nothing

Spec section 11's last row: `/users` is *"reduced to a read-only view of the local user
list, labelled browser-local, not enforced, until the authentication spec lands"*. The spec
then says why this row matters more than the others:

> The `/users` reduction matters. The current screen edits `localStorage` and presents the
> result as access control. Leaving it looking authoritative while `AuthContext.tsx:417`
> accepts any password is the single most misleading surface in the console.

Read the file before you touch it. Eight facts, verified in the working tree:

1. **`UserManagementView.tsx` has five write affordances.** `Reset Defaults` (`:136`–`:147`,
   `restoreDefaults()` behind a `confirm()`), `New User Account` (`:149`–`:156`, opens
   `CreateUserModal`), the per-row `Manage` button (`:437`–`:444`, opens `EditUserModal`), the
   per-cell permission toggle in the matrix (`:538`–`:549`, `toggleUserFeaturePermission`), and
   `Simulate` (`:428`–`:434`, `switchUser`). Four of the five write. The fifth only changes
   which account this browser is pretending to be.

2. **`AuthContext.tsx:98`–`:115` seeds two fabricated audit entries.** `log-001` credits
   `saif.wsm@gmail.com` with creating `elena.rostova@covestro.com`'s account three days ago;
   `log-002` credits the same person with granting `marcus.weber@covestro.com` a permission
   twelve hours ago. Neither event happened. They are the same class of fabrication Task 20
   deletes from `AlarmContext`, and this one is displayed under a compliance heading.

3. **The audit tab calls itself an immutable ledger.** `:621`–`:624`: *"Security & RBAC Audit
   Trail — Immutable ledger tracking user additions, role transitions, and permission
   grants."* It reads `localStorage`, which any operator can edit from a devtools console and
   any browser can clear. Nothing about it is immutable and nothing about it is a ledger.

4. **The matrix advertises persistence it does not have.** `:465`–`:467` badges the matrix
   `LIVE TOGGLE & AUTO-SAVED` and `:470` reads *"Click checkboxes to instantly grant or revoke
   specific console capabilities for any user."* The toggle writes one browser's
   `localStorage` key `uns_rbac_users_v2`. It grants nothing and revokes nothing.

5. **`logAction` is called with actions its own type does not contain.**
   `AuditLogEntry['action']` (`types/rbac.ts:260`) is
   `'CREATE_USER' | 'UPDATE_ROLE' | 'UPDATE_PERMISSIONS' | 'DELETE_USER' | 'TOGGLE_STATUS'`.
   `login` (`:432`) passes `'USER_LOGIN' as any` and `logout` (`:442`) passes
   `'USER_LOGOUT' as any`. The casts exist because the entries are not of the type the ledger
   claims to hold.

6. **`getFeatureIcon` (`:88`–`:111`) has no caller,** and `KeyRound` (`:6`), `Lock` (`:25`) and
   `Sparkles` (`:27`) are imported and never rendered. Deleting `getFeatureIcon` also retires
   the `Layers`, `Radio`, `Workflow`, `Activity`, `Download`, `Send`, `Settings` and `Bookmark`
   imports, which exist only inside it.

7. **The exhaustive caller list for everything this task removes** — run the grep in Step 1 and
   you should get exactly this:

   | Removed member | Callers outside `AuthContext.tsx` |
   | --- | --- |
   | `createUser` | `users/CreateUserModal.tsx:12`, `:44` |
   | `updateUser` | `users/EditUserModal.tsx:13`, `:55` |
   | `deleteUser` | `users/EditUserModal.tsx:13`, `:71` |
   | `resetUserToRoleDefaults` | `users/EditUserModal.tsx:13` |
   | `toggleUserFeaturePermission` | `users/UserManagementView.tsx:49`, `:540` |
   | `restoreDefaults` | `users/UserManagementView.tsx:50`, `:139` |
   | `auditLogs` | `users/UserManagementView.tsx:46`, `:240`, `:627`, `:643` |

   Both modals exist only to drive these methods, so both files go. `switchUser`,
   `hasPermission`, `getUserPermission`, `canAccessTab`, `isAdmin`, `isAuthenticated`, `login`
   and `logout` all have callers elsewhere (`common/UserSessionMenu.tsx`,
   `common/AccessRestricted.tsx`, `layout/AppLayout.tsx`, `layout/Sidebar.tsx`,
   `explore/HistorianTable.tsx`, `simulator/*`, `auth/LoginView.tsx`,
   `landing/LandingView.tsx`, `alarms/AlarmManagementView.tsx`) and all stay.

8. **No test in `11_frontend/src` references `useAuth`, `AuthProvider` or this view.** Nothing
   green breaks; the tests this task writes are the first coverage the screen has ever had.

**What this task does not do.** It does not fix sign-in. Spec section 6 is explicit that
`login` falling through to `users[0]` and ignoring its password argument *"This spec does not
fix it — the authentication spec does"*. It does not touch `LoginView.tsx:245` or
`AuthContext.tsx:73` either — Task 3 owns both. And it does not remove the `/users` route or
its `canAccessTab('users')` gate: an honest read-only directory is worth keeping, because it
is how an integrator sees which role profile changes which part of the console before Cycle 2
makes the roles real.

**Palette note.** This file is dark-only (`bg-[#050505]`, `text-[#F8FAFC]`, `font-mono`) and
this task keeps it that way. Migrating it to the light/dark pairs the new screens use is a
separate change and is not in this spec.

**Files:**
- Modify: `11_frontend/src/components/users/UserManagementView.tsx` (full rewrite, 685 → ~330 lines)
- Delete: `11_frontend/src/components/users/CreateUserModal.tsx`
- Delete: `11_frontend/src/components/users/EditUserModal.tsx`
- Modify: `11_frontend/src/context/AuthContext.tsx`
- Modify: `11_frontend/src/types/rbac.ts:255`–`:261`
- Test: `11_frontend/src/components/users/UserManagementView.test.tsx` (create)
- Test: `11_frontend/src/context/auth-context.test.tsx` (create)

**Interfaces:**
- Consumes: `useAuth` from `src/context/AuthContext.tsx`; `SYSTEM_FEATURES`, `ROLE_CONFIGS`,
  `UserRole` from `src/types/rbac.ts`. Nothing from Tasks 1–20 — this task adds no client
  method, no GraphQL query and no shared component.
- Produces:
  - `AuthContextType` reduced to exactly ten members, in this shape:
    ```ts
    interface AuthContextType {
      currentUser: UserAccount;
      users: UserAccount[];
      isAdmin: boolean;
      isAuthenticated: boolean;
      login: (identifier: string, password?: string) => boolean;
      logout: () => void;
      switchUser: (userId: string) => void;
      hasPermission: (feature: FeatureKey) => boolean;
      getUserPermission: (user: UserAccount, feature: FeatureKey) => boolean;
      canAccessTab: (tab: string) => { allowed: boolean; requiredFeature: FeatureKey; featureName: string };
    }
    ```
    Cycle 2 (`docs/superpowers/plans/2026-09-02-console-authentication.md`) replaces this
    object with an OIDC session, so keep the surface this small.
  - `export const UserManagementView: React.FC` — unchanged signature, no props.
  - Test ids later tasks and Cycle 2 assert against: `users-view`, `users-not-enforced`,
    `users-directory`, `users-matrix`, `users-roles`, `user-row-<id>`, `user-view-as-<id>`.
  - `AuditLogEntry` no longer exists in `src/types/rbac.ts`. `UserAccount`, `UserRole`,
    `FeatureKey`, `SYSTEM_FEATURES` and `ROLE_CONFIGS` are untouched.

- [ ] **Step 1: Confirm the caller list before deleting anything**

Line numbers in this task were read from the working tree, and the file is long enough that an
earlier task's edit can shift them. Match on code content, not on line number, and start by
reproducing the table in fact 7:

```bash
cd 11_frontend/src
for m in createUser updateUser deleteUser resetUserToRoleDefaults \
         toggleUserFeaturePermission restoreDefaults auditLogs; do
  echo "--- $m"
  grep -rn "\b$m\b" --include=*.ts --include=*.tsx . | grep -v "context/AuthContext.tsx"
done
grep -rn "AuditLogEntry" --include=*.ts --include=*.tsx .
```

Expected: the seven blocks match fact 7 exactly, and `AuditLogEntry` appears only in
`context/AuthContext.tsx` (five times) and `types/rbac.ts:255`. If any block names a file this
task does not touch, stop and reconcile before continuing — a caller you did not plan for means
the deletion is not safe yet.

- [ ] **Step 2: Write the failing view test**

Create `11_frontend/src/components/users/UserManagementView.test.tsx`. `AuthProvider` is real
here: it touches only `localStorage`, never `fetch` or `WebSocket`, so `src/test/setup.ts` has
nothing to complain about. Clear storage between tests so the seeded users are deterministic.

```tsx
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AuthProvider } from '../../context/AuthContext';
import { UserManagementView } from './UserManagementView';

const renderView = () =>
  render(
    <AuthProvider>
      <UserManagementView />
    </AuthProvider>
  );

describe('UserManagementView', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('says the accounts are browser-local and not enforced', () => {
    renderView();
    const notice = screen.getByTestId('users-not-enforced');
    expect(notice).toHaveTextContent(/browser-local, not enforced/i);
    expect(notice).toHaveTextContent(/accepts any password/i);
  });

  it('offers no way to create, edit, delete or reset an account', () => {
    renderView();
    expect(screen.queryByRole('button', { name: /new user account/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /reset defaults/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /manage/i })).toBeNull();
    expect(screen.queryByText(/ADMIN ACCESS ONLY/i)).toBeNull();
  });

  it('renders the feature matrix without a single toggle', () => {
    renderView();
    fireEvent.click(screen.getByRole('button', { name: /feature flags/i }));
    const matrix = screen.getByTestId('users-matrix');
    expect(matrix.querySelectorAll('button')).toHaveLength(0);
    expect(screen.queryByText(/auto-saved/i)).toBeNull();
    expect(screen.queryByText(/instantly grant or revoke/i)).toBeNull();
  });

  it('has no audit log tab', () => {
    renderView();
    expect(screen.queryByRole('button', { name: /audit/i })).toBeNull();
    expect(screen.queryByText(/immutable ledger/i)).toBeNull();
  });

  it('still lets an integrator view the console as another account', () => {
    renderView();
    // The seeded default account is the admin; the engineer is a different row.
    expect(screen.getByTestId('user-row-usr-admin-01')).toHaveTextContent('YOU');
    fireEvent.click(screen.getByTestId('user-view-as-usr-eng-01'));
    expect(screen.getByTestId('user-row-usr-eng-01')).toHaveTextContent('YOU');
    expect(screen.getByTestId('user-row-usr-admin-01')).not.toHaveTextContent('YOU');
  });
});
```

The engineer's id is read from `AuthContext.tsx`'s `INITIAL_USERS` — confirm it with
`grep -n "id: 'usr-" 11_frontend/src/context/AuthContext.tsx` and use the real second id if it
is not `usr-eng-01`.

- [ ] **Step 3: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/components/users/UserManagementView.test.tsx`

Expected: FAIL. The first test cannot find `users-not-enforced`; the second finds
`New User Account`, `Reset Defaults`, `Manage` and `ADMIN ACCESS ONLY`; the third finds
`LIVE TOGGLE & AUTO-SAVED` and forty-odd toggle buttons; the fourth finds the audit tab; the
fifth cannot find `user-row-usr-admin-01`.

- [ ] **Step 4: Rewrite the view**

Replace the whole of `11_frontend/src/components/users/UserManagementView.tsx` with:

```tsx
import React, { useMemo, useState } from 'react';
import {
  Users,
  Shield,
  Search,
  Filter,
  CheckCircle2,
  XCircle,
  Clock,
  Check,
  X,
  FileSpreadsheet,
  Eye,
  Info,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { UserRole, SYSTEM_FEATURES, ROLE_CONFIGS } from '../../types/rbac';

type SubTab = 'directory' | 'matrix' | 'roles';

export const UserManagementView: React.FC = () => {
  const { users, currentUser, switchUser } = useAuth();

  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  const filteredUsers = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return users.filter((u) => {
      const matchSearch =
        u.name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        u.department.toLowerCase().includes(q) ||
        u.plantLocation.toLowerCase().includes(q);
      const matchRole = roleFilter === 'ALL' || u.role === roleFilter;
      const matchStatus = statusFilter === 'ALL' || u.status === statusFilter;
      return matchSearch && matchRole && matchStatus;
    });
  }, [users, searchQuery, roleFilter, statusFilter]);

  const stats = useMemo(
    () => ({
      total: users.length,
      admins: users.filter((u) => u.role === 'admin').length,
      engineers: users.filter((u) => u.role === 'engineer').length,
      operators: users.filter((u) => u.role === 'operator').length,
      auditors: users.filter((u) => u.role === 'auditor').length,
      suspended: users.filter((u) => u.status === 'suspended').length,
    }),
    [users]
  );

  const subTabClass = (tab: SubTab) =>
    `px-3 py-2 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
      activeSubTab === tab
        ? 'border-[#FFC107] text-[#FFC107]'
        : 'border-transparent text-[#94A3B8] hover:text-[#F8FAFC]'
    } focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500`;

  return (
    <div
      id="user-management-view"
      data-testid="users-view"
      className="flex-1 flex flex-col h-full overflow-hidden bg-[#050505] text-[#F8FAFC] font-mono text-xs"
    >
      {/* Header */}
      <div className="p-3 md:p-4 bg-[#111114] border-b border-[#1E293B] shrink-0 flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-[#0B0B0C] border border-[#1E293B] flex items-center justify-center text-[#94A3B8]">
          <Shield className="w-4 h-4" />
        </div>
        <div>
          <h1 className="font-bold text-sm text-[#F8FAFC]">Console Users</h1>
          <p className="text-[10px] text-[#64748B]">
            The accounts this browser knows about, the role profile each one was created from,
            and which parts of the console each profile shows.
          </p>
        </div>
      </div>

      {/* The one thing an operator has to know before reading anything below */}
      <div
        data-testid="users-not-enforced"
        className="px-3 md:px-4 py-2.5 bg-[#0B0B0C] border-b border-[#1E293B] shrink-0 flex items-start gap-2.5"
      >
        <Info className="w-3.5 h-3.5 text-[#FFC107] mt-0.5 shrink-0" />
        <p className="text-[11px] leading-relaxed text-[#94A3B8] max-w-4xl">
          <span className="font-bold text-[#F8FAFC]">Browser-local, not enforced.</span> This
          list, the role profiles and every flag below are stored in this browser only. Nothing
          here is sent to the platform, the GraphQL API applies no authorization of its own, and
          signing in accepts any password. Read this screen as a preview of how the console
          changes shape per role — not as access control.
        </p>
      </div>

      {/* Counts of the local list */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 p-3 bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] shrink-0">
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Accounts</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.total}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Admins</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.admins}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Engineers</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.engineers}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Operators</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.operators}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Auditors</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.auditors}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Suspended</div>
          <div className="text-base font-bold text-[#94A3B8]">{stats.suspended}</div>
        </div>
      </div>

      {/* Sub-navigation */}
      <div className="px-3 md:px-4 bg-[#111114] border-b border-[#1E293B] flex items-center shrink-0 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-1 min-w-max">
          <button
            id="subtab-directory"
            type="button"
            onClick={() => setActiveSubTab('directory')}
            className={subTabClass('directory')}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Directory ({filteredUsers.length})</span>
          </button>

          <button
            id="subtab-matrix"
            type="button"
            onClick={() => setActiveSubTab('matrix')}
            className={subTabClass('matrix')}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span>Feature flags</span>
          </button>

          <button
            id="subtab-roles"
            type="button"
            onClick={() => setActiveSubTab('roles')}
            className={subTabClass('roles')}
          >
            <Shield className="w-3.5 h-3.5" />
            <span>Role profiles</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 md:p-4 scrollbar-thin scrollbar-thumb-[#1E293B]">
        {/* DIRECTORY */}
        {activeSubTab === 'directory' && (
          <div className="space-y-3" data-testid="users-directory">
            <div className="p-2.5 rounded bg-[#111114] border border-[#1E293B] flex flex-wrap items-center justify-between gap-2.5">
              <div className="relative flex-1 min-w-[200px] max-w-md">
                <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-2 pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search name, email, department, site..."
                  aria-label="Search accounts"
                  className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded pl-8 pr-3 py-1 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                />
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <Filter className="w-3 h-3 text-[#64748B]" />
                  <span className="text-[10px] text-[#64748B] uppercase">Role:</span>
                  <select
                    value={roleFilter}
                    onChange={(e) => setRoleFilter(e.target.value)}
                    aria-label="Filter by role"
                    className="bg-[#0B0B0C] border border-[#1E293B] rounded px-2 py-1 text-[11px] text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                  >
                    <option value="ALL">All roles</option>
                    <option value="admin">Admin</option>
                    <option value="engineer">Engineer</option>
                    <option value="operator">Operator</option>
                    <option value="auditor">Auditor</option>
                    <option value="viewer">Viewer</option>
                  </select>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[#64748B] uppercase">Status:</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    aria-label="Filter by status"
                    className="bg-[#0B0B0C] border border-[#1E293B] rounded px-2 py-1 text-[11px] text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                  >
                    <option value="ALL">All statuses</option>
                    <option value="active">Active</option>
                    <option value="suspended">Suspended</option>
                    <option value="pending">Pending</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="border border-[#1E293B] rounded-lg bg-[#111114] overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs font-mono">
                  <thead>
                    <tr className="bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] text-[#64748B] uppercase tracking-wider">
                      <th className="py-2.5 px-3">Account</th>
                      <th className="py-2.5 px-3">Role profile</th>
                      <th className="py-2.5 px-3">Plant &amp; department</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Feature flags set</th>
                      <th className="py-2.5 px-3">Last used here</th>
                      <th className="py-2.5 px-3 text-right">View console as</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E293B]">
                    {filteredUsers.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="text-center py-10 text-[#64748B]">
                          No account matches this search. Clear the filters to see all{' '}
                          {users.length}.
                        </td>
                      </tr>
                    ) : (
                      filteredUsers.map((user) => {
                        const isSelf = user.id === currentUser.id;
                        const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                        const allowedCount = Object.values(user.customPermissions || {}).filter(
                          Boolean
                        ).length;

                        return (
                          <tr
                            key={user.id}
                            data-testid={`user-row-${user.id}`}
                            className={`hover:bg-[#1E293B]/40 transition-colors ${
                              isSelf ? 'bg-[#1E293B]/20' : ''
                            }`}
                          >
                            <td className="py-2.5 px-3">
                              <div className="flex items-center gap-2.5">
                                <div
                                  className={`w-7 h-7 rounded-full ${
                                    user.avatarColor || 'bg-[#FFC107]'
                                  } text-black flex items-center justify-center font-bold text-xs shrink-0`}
                                >
                                  {user.name.charAt(0).toUpperCase()}
                                </div>
                                <div className="min-w-0">
                                  <div className="font-bold text-[#F8FAFC] flex items-center gap-1.5 truncate">
                                    <span>{user.name}</span>
                                    {isSelf && (
                                      <span className="px-1 rounded bg-amber-500/20 text-[#FFC107] text-[8px] font-bold border border-amber-500/30">
                                        YOU
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-[10px] text-[#64748B] truncate">
                                    {user.email}
                                  </div>
                                </div>
                              </div>
                            </td>

                            <td className="py-2.5 px-3">
                              <span
                                className={`px-2 py-0.5 rounded text-[9px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}
                              >
                                {roleConfig.label.toUpperCase()}
                              </span>
                            </td>

                            <td className="py-2.5 px-3">
                              <div className="text-[11px] text-[#F8FAFC] truncate max-w-[150px]">
                                {user.department}
                              </div>
                              <div className="text-[9px] text-[#64748B] truncate max-w-[150px]">
                                {user.plantLocation}
                              </div>
                            </td>

                            <td className="py-2.5 px-3">
                              {user.status === 'active' && (
                                <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px]">
                                  <CheckCircle2 className="w-3 h-3" />
                                  <span>Active</span>
                                </span>
                              )}
                              {user.status === 'suspended' && (
                                <span className="inline-flex items-center gap-1 text-rose-400 text-[10px]">
                                  <XCircle className="w-3 h-3" />
                                  <span>Suspended</span>
                                </span>
                              )}
                              {user.status === 'pending' && (
                                <span className="inline-flex items-center gap-1 text-amber-400 text-[10px]">
                                  <Clock className="w-3 h-3" />
                                  <span>Pending</span>
                                </span>
                              )}
                            </td>

                            <td className="py-2.5 px-3">
                              <span className="font-bold text-[#F8FAFC]">{allowedCount}</span>
                              <span className="text-[#64748B]"> / {SYSTEM_FEATURES.length}</span>
                            </td>

                            <td className="py-2.5 px-3 text-[10px] text-[#64748B]">
                              {user.lastLogin === 'Never'
                                ? 'Never'
                                : new Date(user.lastLogin).toLocaleString(undefined, {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })}
                            </td>

                            <td className="py-2.5 px-3 text-right">
                              {isSelf ? (
                                <span className="text-[10px] text-[#64748B]">Current</span>
                              ) : (
                                <button
                                  type="button"
                                  data-testid={`user-view-as-${user.id}`}
                                  onClick={() => switchUser(user.id)}
                                  className="px-2 py-1 rounded bg-[#0B0B0C] border border-[#1E293B] hover:border-[#FFC107] text-[#94A3B8] hover:text-[#FFC107] text-[10px] inline-flex items-center gap-1 transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                                  title={`Show this console as ${user.name} sees it`}
                                >
                                  <Eye className="w-3 h-3" />
                                  <span>View as</span>
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* FEATURE FLAGS */}
        {activeSubTab === 'matrix' && (
          <div className="space-y-3" data-testid="users-matrix">
            <div className="p-3 bg-[#111114] border border-[#1E293B] rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-2">
              <div>
                <h3 className="font-bold text-xs text-[#F8FAFC]">Feature flags by account</h3>
                <p className="text-[10px] text-[#64748B] max-w-3xl leading-relaxed">
                  Which console features each account sees. A flag is set from the role profile
                  the account was created with, and is stored in this browser. It is not a
                  permission the platform checks.
                </p>
              </div>

              <div className="text-[10px] text-[#94A3B8] flex items-center gap-3 shrink-0">
                <div className="flex items-center gap-1">
                  <Check className="w-3 h-3 text-emerald-400" />
                  <span>Set</span>
                </div>
                <div className="flex items-center gap-1">
                  <X className="w-3 h-3 text-[#475569]" />
                  <span>Not set</span>
                </div>
              </div>
            </div>

            <div className="border border-[#1E293B] rounded-lg bg-[#111114] overflow-x-auto shadow-sm">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] text-[#64748B] uppercase tracking-wider">
                    <th className="py-2.5 px-3 sticky left-0 bg-[#0B0B0C] z-10 min-w-[180px]">
                      Account
                    </th>
                    <th className="py-2.5 px-2 text-center min-w-[70px]">Role</th>
                    {SYSTEM_FEATURES.map((f) => (
                      <th
                        key={f.key}
                        className="py-2.5 px-2 text-center min-w-[100px]"
                        title={f.description}
                      >
                        <div className="truncate">{f.label}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E293B]">
                  {users.map((user) => {
                    const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                    const bypassesFlags = user.role === 'admin';

                    return (
                      <tr key={user.id} className="hover:bg-[#1E293B]/30 transition-colors">
                        <td className="py-2.5 px-3 sticky left-0 bg-[#111114] z-10 border-r border-[#1E293B]">
                          <div className="flex items-center gap-2">
                            <div
                              className={`w-5 h-5 rounded-full ${
                                user.avatarColor || 'bg-[#FFC107]'
                              } text-black flex items-center justify-center font-bold text-[10px] shrink-0`}
                            >
                              {user.name.charAt(0).toUpperCase()}
                            </div>
                            <div className="truncate">
                              <div className="font-bold text-[#F8FAFC] truncate text-[11px]">
                                {user.name}
                              </div>
                              <div className="text-[9px] text-[#64748B] truncate">
                                {user.email}
                              </div>
                            </div>
                          </div>
                        </td>

                        <td className="py-2 px-2 text-center border-r border-[#1E293B]">
                          <span
                            className={`px-1.5 rounded text-[8px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}
                          >
                            {user.role.toUpperCase()}
                          </span>
                        </td>

                        {SYSTEM_FEATURES.map((feat) => {
                          const isSet = bypassesFlags || !!user.customPermissions?.[feat.key];

                          return (
                            <td key={feat.key} className="py-2 px-2 text-center">
                              {isSet ? (
                                <Check
                                  className="w-3.5 h-3.5 text-emerald-400 inline-block"
                                  aria-label={`${feat.label} set for ${user.name}`}
                                  title={
                                    bypassesFlags
                                      ? 'The admin role shows every feature regardless of flags'
                                      : `${feat.label} set for ${user.name}`
                                  }
                                />
                              ) : (
                                <X
                                  className="w-3.5 h-3.5 text-[#475569] inline-block"
                                  aria-label={`${feat.label} not set for ${user.name}`}
                                  title={`${feat.label} not set for ${user.name}`}
                                />
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ROLE PROFILES */}
        {activeSubTab === 'roles' && (
          <div className="space-y-3" data-testid="users-roles">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                const config = ROLE_CONFIGS[r];
                const assignedCount = users.filter((u) => u.role === r).length;

                return (
                  <div
                    key={r}
                    className="p-4 rounded-lg bg-[#111114] border border-[#1E293B] space-y-3 shadow-sm hover:border-[#334155] transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span
                        className={`px-2.5 py-0.5 rounded text-[10px] font-bold border ${config.badgeBg} ${config.badgeText} ${config.badgeBorder}`}
                      >
                        {config.label.toUpperCase()}
                      </span>
                      <span className="text-[10px] text-[#64748B]">
                        {assignedCount} in this browser
                      </span>
                    </div>

                    <p className="text-[11px] text-[#94A3B8] leading-relaxed">
                      {config.description}
                    </p>

                    <div className="pt-2 border-t border-[#1E293B] space-y-1.5">
                      <div className="text-[9px] uppercase tracking-wider text-[#64748B]">
                        Features this profile shows
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {SYSTEM_FEATURES.map((feat) => {
                          const isDefault = !!config.defaultPermissions[feat.key];
                          return (
                            <span
                              key={feat.key}
                              className={`px-1.5 py-0.5 rounded text-[9px] flex items-center gap-1 border ${
                                isDefault
                                  ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-400'
                                  : 'bg-[#0B0B0C] border-[#1E293B] text-[#475569]'
                              }`}
                            >
                              {isDefault ? (
                                <Check className="w-2.5 h-2.5" />
                              ) : (
                                <X className="w-2.5 h-2.5" />
                              )}
                              <span>{feat.label}</span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
```

Three details worth naming, because a reviewer will ask:

- The matrix renders `Check`/`X` **icons with `aria-label`**, not buttons and not bare glyphs.
  `matrix.querySelectorAll('button')` returning zero is the test that this screen cannot write,
  and the labels keep the cell readable to a screen reader now that the `title` is no longer
  attached to an interactive element.
- The admin row still shows every flag set, because `getUserPermission` genuinely returns
  `true` for `role === 'admin'` before it looks at `customPermissions`. The `title` says so
  rather than implying the flags were individually granted.
- `Last used here` replaces `Last Active`. `lastLogin` is written by `switchUser` and `login`
  in this browser, so "active" overstated it.

- [ ] **Step 5: Delete the two modals**

```bash
cd 11_frontend
git rm src/components/users/CreateUserModal.tsx src/components/users/EditUserModal.tsx
```

They are the only callers of `createUser`, `updateUser`, `deleteUser` and
`resetUserToRoleDefaults`, and nothing else imports them — Step 4 removed the two import lines
that did.

- [ ] **Step 6: Run the view test**

Run: `cd 11_frontend && npx vitest run src/components/users/UserManagementView.test.tsx`

Expected: PASS, five tests.

- [ ] **Step 7: Commit the view**

```bash
cd 11_frontend
git add src/components/users/UserManagementView.tsx src/components/users/UserManagementView.test.tsx
git commit -m "refactor(frontend): make /users a read-only, browser-local account list

The screen edited localStorage and presented the result as access control.
Create, edit, delete, reset and the permission toggle are gone, along with
the ADMIN ACCESS ONLY badge and the LIVE TOGGLE & AUTO-SAVED claim. A notice
states that the list is browser-local, not enforced, and that sign-in accepts
any password. 'View as' stays: it is how a role preview is reached."
```

- [ ] **Step 8: Write the failing context-shape test**

Create `11_frontend/src/context/auth-context.test.tsx`. Asserting the whole sorted key list is
deliberate: it fails when someone adds a write method back, which a per-method
`toBeUndefined()` check would not.

```tsx
import { describe, expect, it, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';

type Auth = ReturnType<typeof useAuth>;

let captured: Auth | null = null;

const Probe: React.FC = () => {
  captured = useAuth();
  return null;
};

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear();
    captured = null;
  });

  it('exposes no way to write an account, a permission or an audit entry', () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    expect(Object.keys(captured!).sort()).toEqual([
      'canAccessTab',
      'currentUser',
      'getUserPermission',
      'hasPermission',
      'isAdmin',
      'isAuthenticated',
      'login',
      'logout',
      'switchUser',
      'users',
    ]);
  });

  it('clears an audit trail left in storage by an earlier build', () => {
    localStorage.setItem(
      'uns_rbac_audit_logs_v2',
      JSON.stringify([{ id: 'log-001', details: 'Created Engineer account' }])
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    expect(localStorage.getItem('uns_rbac_audit_logs_v2')).toBeNull();
  });
});
```

Add `import React from 'react';` at the top if the project's JSX runtime is not automatic —
check the top of `AlarmContext`'s test from Task 20 and match it.

- [ ] **Step 9: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/context/auth-context.test.tsx`

Expected: FAIL. The first test reports seven extra keys (`auditLogs`, `createUser`,
`deleteUser`, `restoreDefaults`, `resetUserToRoleDefaults`, `toggleUserFeaturePermission`,
`updateUser`). The second finds the stale key still in storage.

- [ ] **Step 10: Delete the fabricated audit entries and their storage key**

In `11_frontend/src/context/AuthContext.tsx`, delete `INITIAL_AUDIT_LOGS` in full — the
`const INITIAL_AUDIT_LOGS: AuditLogEntry[] = [ … ];` block at `:98`–`:115`, both entries.

Then narrow `STORAGE_KEYS` (`:17`–`:22`) by removing the `AUDIT_LOGS` line:

```ts
const STORAGE_KEYS = {
  USERS: 'uns_rbac_users_v2',
  CURRENT_USER_ID: 'uns_rbac_current_user_id_v2',
  IS_LOGGED_IN: 'uns_rbac_logged_in_v2',
};
```

And fix the file's header comment (`:1`–`:5`) so it stops promising an audit log:

```ts
/**
 * Console session state, stored in this browser.
 * Holds the local account list, which account the console is being viewed as, and the
 * feature flags each account carries. It authenticates nothing: the platform applies no
 * authorization to GraphQL, and login ignores its password argument. Real authentication
 * is a separate change — see docs/adr/.
 */
```

- [ ] **Step 11: Delete the audit state, the writer, and every mutation**

Still in `AuthContext.tsx`, delete these six regions. Match them by their opening line, not by
line number:

1. `const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>(() => { … });` (`:172`–`:183`).
2. The `useEffect` that persists it (`:211`–`:217`) — the one whose body is
   `localStorage.setItem(STORAGE_KEYS.AUDIT_LOGS, JSON.stringify(auditLogs));`.
3. `const logAction = useCallback(…)` (`:223`–`:236`).
4. `createUser` (`:249`–`:272`), `updateUser` (`:274`–`:293`), `deleteUser` (`:295`–`:307`),
   `toggleUserFeaturePermission` (`:309`–`:330`) and `resetUserToRoleDefaults` (`:332`–`:356`)
   — five consecutive `useCallback` blocks. `deleteUser` is also the file's only `alert()`.
5. `const restoreDefaults = useCallback(…)` (`:445`–`:458`).
6. The seven matching lines from the `interface AuthContextType` body (`:120`, `:126`–`:130`,
   `:134`) and the seven from the provider's `value` object (`:465`, `:471`–`:475`, `:479`),
   leaving the ten members listed in this task's Produces block.

`login` and `logout` each end with a `logAction(… as any, …)` call. Drop those two lines; the
casts existed only because the actions were outside `AuditLogEntry['action']`. `login` keeps
`setCurrentUserId`, `setIsAuthenticated` and the `lastLogin` update, and its dependency array
becomes `[users]`; `logout` keeps `setIsAuthenticated(false)` and its array becomes `[]`.

Add the one-time cleanup for browsers that already hold the fabricated entries, next to the
other persistence effects:

```ts
  // An earlier build seeded a browser-local "audit trail" with events that never happened.
  // Anything still in storage is that fabrication, so drop it once on mount.
  useEffect(() => {
    try {
      localStorage.removeItem('uns_rbac_audit_logs_v2');
    } catch {
      // ignore
    }
  }, []);
```

The key is written as a literal because `STORAGE_KEYS.AUDIT_LOGS` no longer exists — that is
the point.

Finally, narrow the type import (`:8`–`:15`). `AuditLogEntry` and `UserRole` lose their last
use in this file, and `SYSTEM_FEATURES` was already imported without ever being used:

```ts
import { UserAccount, FeatureKey, ROLE_CONFIGS } from '../types/rbac';
```

`ROLE_CONFIGS` stays — `INITIAL_USERS` still spreads five `defaultPermissions` from it.
`FeatureKey` stays — `hasPermission`, `getUserPermission` and `canAccessTab` all use it.

- [ ] **Step 12: Run the context test**

Run: `cd 11_frontend && npx vitest run src/context/auth-context.test.tsx`

Expected: PASS, two tests.

- [ ] **Step 13: Delete `AuditLogEntry` from the type module**

Nothing imports it now. Remove `11_frontend/src/types/rbac.ts:255`–`:261` in full:

```ts
export interface AuditLogEntry {
  id: string;
  timestamp: string;
  actorEmail: string;
  targetUserEmail: string;
  action: 'CREATE_USER' | 'UPDATE_ROLE' | 'UPDATE_PERMISSIONS' | 'DELETE_USER' | 'TOGGLE_STATUS';
  details: string;
}
```

Then prove it is unreferenced:

```bash
cd 11_frontend && grep -rn "AuditLogEntry" src/ ; echo "exit=$?"
```

Expected: no output, `exit=1`.

- [ ] **Step 14: Type-check and run the whole suite**

```bash
cd 11_frontend
npx tsc --noEmit
npx vitest run
```

Expected: `tsc` clean, all tests pass. If `tsc` reports an unused import in
`UserManagementView.tsx`, the rewrite in Step 4 was applied on top of the old import block
instead of replacing it — the new list is exactly twelve `lucide-react` names and three from
`types/rbac`.

- [ ] **Step 15: Commit**

```bash
cd 11_frontend
git add src/context/AuthContext.tsx src/context/auth-context.test.tsx src/types/rbac.ts
git commit -m "refactor(frontend): delete the browser-local RBAC write surface

INITIAL_AUDIT_LOGS credited named people with account changes that never
happened and presented them as an immutable ledger. It is gone, along with
the state, the writer, the storage key, and the five mutations plus
restoreDefaults that fed it. A mount-once removeItem clears the entries from
browsers that already stored them. AuthContext is down to ten read members;
Cycle 2 replaces them with an OIDC session."
```

**Definition of done:**
- `/users` has no control that writes: no create, no edit, no delete, no reset, no toggle.
- The screen states `Browser-local, not enforced`, that nothing is sent to the platform, that
  GraphQL applies no authorization, and that sign-in accepts any password.
- `ADMIN ACCESS ONLY`, `LIVE TOGGLE & AUTO-SAVED`, *"instantly grant or revoke"*, *"Immutable
  ledger"* and *"compliance logs"* appear nowhere in `11_frontend/src`.
- The Security Audit Log sub-tab is gone; three sub-tabs remain — Directory, Feature flags,
  Role profiles.
- `View as` still switches the previewed account, and the `YOU` marker follows it.
- `AuthContext` exposes exactly ten members, asserted as a sorted key list.
- `uns_rbac_audit_logs_v2` is removed from storage on mount and written by nothing.
- `AuditLogEntry` does not exist in `src/`; `grep -rn AuditLogEntry src/` is empty.
- `CreateUserModal.tsx` and `EditUserModal.tsx` are deleted.
- `login` still ignores its password argument. That is Cycle 2's task, and this screen now says
  so out loud instead of hiding it behind a red badge.
- `npx tsc --noEmit` clean; `npx vitest run` green.

---

## Task 22: SPARKPLUG — the browser decodes nothing, and says nothing it cannot check

Spec section 18's test 14 is the requirement:

> **No Sparkplug decoding in the browser.** Live Sparkplug renders as a badge over
> `BytesPayload`; decoded values come only from `getSpbNodesByMetric`.

Spec section 3's finding 7 says the *decoding* half is already right: *"Sparkplug is already
handled correctly. `lib/uns/sparkplug.ts` defines `SPARKPLUG_PREFIX`, and no browser code
decodes protobuf."* That finding holds — nothing in `11_frontend/src` parses a protobuf. But
reading the three files that render Sparkplug turned up six statements the console cannot
support, and one stale-state bug. This task locks the rule down with tests and fixes those.

**Where the decoding actually happens.** Get this right before you edit the copy, because two
files currently attribute it to the wrong module:

- `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py:306`–`:308` calls
  `convert_spb_bytes_payload_to_dict(payload)` for messages in the `spBv1.0` namespace. Every
  subscriber built on the shared listener therefore receives a decoded payload.
- `03_uns_graphdb` projects those messages into Neo4j under the node labels in
  `graphdb_config.py:90`–`:92` (`spBv1_0`, `GROUP`, `MESSAGE_TYPE`, `EDGE_NODE`, `DEVICE`).
- `07_uns_graphql/src/uns_graphql/queries/graph.py:382`–`:409` — `get_spb_nodes_by_metric` runs
  `_SEARCH_SPB_BY_METRIC_QUERY` against the graph and returns `SPBNode`s. It is a read. It
  decodes nothing off the wire.
- `05_sparkplugb` is a separate decoder application: its README says it subscribes to
  `spBv1.0/#`, decodes, maps metric names onto the ISA-95 namespace, and republishes — and that
  it is *"**not** a SCADA/IIOT host and will not be publishing any control messages"*.

So `SparkplugView.tsx:93` (*"Decoded edge nodes & metrics from 07_uns_graphql Sparkplug
mapper"*) and `PayloadInspector.tsx:264` (*"Decoded by 07_uns_graphql Sparkplug mapper."*) both
credit the wrong component. GraphQL is where the console *reads* decoded metrics, not where
decoding happens.

**The six unsupported statements and the bug.** All verified in the working tree:

1. **`map-nodes.ts:139` hardcodes `online: true`.** `graphqlSpbNodeToSparkplugNode` sets it on
   every node it builds, and `SparkplugNode.online` (`types/uns.ts:76`) is a required boolean
   that nothing ever sets to `false`. `getSpbNodesByMetric` returns whatever the graph holds;
   liveness is not in the payload. Nothing in `src` reads `.online` either — grep it.
2. **`SparkplugView.tsx:152` renders a glowing green dot** on every node header regardless of
   that field. Same claim, hardcoded a second time.
3. **`map-nodes.ts:105` computes `binaryByteSize` as `value.length / 2`.** The value is the
   string from `SPBPrimitive.data` or `BytesPayload.data`, and
   `07_uns_graphql/src/uns_graphql/type/basetype.py:47`–`:52` defines `BytesPayload.data` as
   `strawberry.scalars.Base64` — *"Represents Bytes data encoded as base64"*. Halving a base64
   length is a hex assumption, so the byte count printed on screen is wrong.
4. **`SparkplugView.tsx:49` falls back to `32`** when `binaryByteSize` is absent, so the UI can
   print `[Binary Data: 32 bytes]` for a payload whose size it does not know. Same family as
   `Nodes: {allLoadedNodes.length || 28}` in spec section 11.
5. **`SparkplugView.tsx:158` renders `Seq: #{node.sequenceNumber ?? 0}`.** `SPBNode.seq` is
   non-nullable in the schema (`type/sparkplugb_node.py:317`, `seq: int`), so the `?? 0` never
   fires — but it is a fabricated default sitting in the render path, and the optional
   `sequenceNumber?: number` in `types/uns.ts:74` is what invites it.
6. **`SparkplugView.tsx:43` hardcodes an enterprise name.**
   `name.startsWith('CovestroAG') || name.split('/').length >= 3` decides whether the
   `Open in UNS` button appears. `05_sparkplugb`'s mapping rule is simply that the metric
   **name** carries the ISA-95 path, so the plant-specific prefix and the `>= 3` guess are both
   noise: any name containing `/` is a namespace path.
7. **The stale-query bug.** `metricQuery` is initialised from `sparkplugInitialMetric`
   (`:17`) but the effect at `:37`–`:39` depends on `sparkplugInitialMetric` and calls
   `fetchSpbData()`, which reads `metricQuery`. `UNSContext.tsx:330`–`:334`'s `jumpToSparkplug`
   sets the metric and changes the hash while this screen may already be mounted, in which case
   `useState`'s initialiser does not run again: the second jump queries the **first** metric and
   the search box still shows it. Reproduce it by opening a Sparkplug node in PayloadInspector,
   coming back, and opening a different one.

Two more things this task deliberately leaves alone, so nobody "fixes" them later without
reading this:

- **`queries.ts` asks for `uuid` and `body`** on every `getSpbNodesByMetric` call, and
  `GraphqlSpbNode` (`services/graphql/types.ts:123`–`:124`) types them as optional. Nothing maps
  or renders either one. `body` is `strawberry.scalars.Base64` — *"array of bytes used for any
  custom binary encoded data"* (`type/sparkplugb_node.py:320`). Pulling an undecodable binary
  blob into a browser that must not decode it, to then discard it, is worth one line of
  deletion, so this task **does** remove both. That is the exception; the next item is not.
- **`map-nodes.ts:87`–`:89`'s `BytesPayload` branch in `spbMetricValue` is unreachable** — the
  branch above it (`:78`, `'data' in value && typeof value.data === 'string'`) already catches
  base64 strings, which is what `BytesPayload.data` is. It is dead but harmless, and deleting it
  is the kind of change that reads as behavioural in review. Leave it. If a later reader wants
  it gone, the reasoning is here.

**Files:**
- Create: `11_frontend/src/lib/uns/base64.ts`
- Modify: `11_frontend/src/lib/uns/map-nodes.ts` (the `binaryByteSize` line and `online: true`)
- Modify: `11_frontend/src/types/uns.ts` (`SparkplugNode`)
- Modify: `11_frontend/src/services/graphql/queries.ts` (`GET_SPB_NODES_BY_METRIC_QUERY`)
- Modify: `11_frontend/src/services/graphql/types.ts:118`–`:125` (`GraphqlSpbNode`)
- Modify: `11_frontend/src/components/sparkplug/SparkplugView.tsx`
- Modify: `11_frontend/src/components/home/PayloadInspector.tsx:256`–`:273`
- Modify: `11_frontend/src/context/UNSContext.tsx:364`–`:374` (the feed guard, Step 17)
- Test: `11_frontend/src/lib/uns/base64.test.ts` (create)
- Test: `11_frontend/src/components/sparkplug/SparkplugView.test.tsx` (create)
- Test: `11_frontend/src/context/UNSContext.feed.test.tsx` (create)
- Test: `11_frontend/src/components/home/LiveMqttFeed.sparkplug.test.tsx` (create)

**Interfaces:**
- Consumes: `unsGraphQLClient.getSpbNodesByMetric(metricNames: string[]): Promise<SparkplugNode[]>`
  — already in the repo at `client.ts:382`, unchanged by this task and by every other task in
  this plan. `useUNS()` for `jumpToTopicInTree` and `sparkplugInitialMetric`.
- Produces:
  - `src/lib/uns/base64.ts`:
    ```ts
    /** Byte length of a base64 string, without decoding it. Returns null if it is not base64. */
    export function base64ByteLength(data: string): number | null;
    ```
  - `SparkplugNode` in `src/types/uns.ts` loses `online` and requires `sequenceNumber`:
    ```ts
    export interface SparkplugNode {
      groupId: string;
      edgeNodeId: string;
      deviceId?: string;
      topic: string;
      metrics: SparkplugMetric[];
      sequenceNumber: number;
      timestamp: string;
    }
    ```
    `SparkplugMetric` is unchanged, including the optional `binaryByteSize?: number` — it is now
    absent rather than wrong when the size cannot be established.
  - `GraphqlSpbNode` in `src/services/graphql/types.ts` loses `uuid` and `body`.
  - Test ids: `spb-node`, `spb-metric-row`, `spb-binary`, `spb-empty`, `spb-search`.

- [ ] **Step 1: Write the failing base64 test**

Create `11_frontend/src/lib/uns/base64.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { base64ByteLength } from './base64';

describe('base64ByteLength', () => {
  it('counts bytes for each padding case', () => {
    expect(base64ByteLength('AAECAw==')).toBe(4); // 00 01 02 03
    expect(base64ByteLength('AAECAwQ=')).toBe(5);
    expect(base64ByteLength('AAECAwQF')).toBe(6);
    expect(base64ByteLength('')).toBe(0);
  });

  it('returns null rather than a wrong number for anything that is not base64', () => {
    expect(base64ByteLength('not base64!')).toBeNull();
    expect(base64ByteLength('AAE')).toBeNull(); // length 3 cannot be base64
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/lib/uns/base64.test.ts`

Expected: FAIL — `Failed to resolve import "./base64"`.

- [ ] **Step 3: Write `base64.ts`**

Create `11_frontend/src/lib/uns/base64.ts`:

```ts
/**
 * The size of a base64 payload, measured without decoding it.
 *
 * The console never decodes Sparkplug bytes — 07_uns_graphql hands them over as
 * strawberry.scalars.Base64 and they stay that way in the browser. A byte count is still
 * useful to an integrator, and base64 gives one exactly: four characters carry three bytes,
 * minus one byte per '=' of padding.
 *
 * Returns null when the string is not valid base64, because a wrong size is worse than none.
 */
export function base64ByteLength(data: string): number | null {
  if (data.length === 0) {
    return 0
  }
  if (data.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(data)) {
    return null
  }
  const padding = data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0
  return (data.length / 4) * 3 - padding
}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd 11_frontend && npx vitest run src/lib/uns/base64.test.ts`

Expected: PASS, two tests.

- [ ] **Step 5: Stop the mapper inventing a byte count and a liveness flag**

In `11_frontend/src/lib/uns/map-nodes.ts`, add the import beside the existing
`./sparkplug` import:

```ts
import { base64ByteLength } from './base64'
```

Replace the `binaryByteSize` line (`:105`):

```ts
    binaryByteSize: isBinary && typeof value === 'string' ? value.length / 2 : undefined,
```

with:

```ts
    // BytesPayload.data is base64 (07_uns_graphql type/basetype.py). Undefined when the
    // string is not base64 — the screen then says "Binary data" with no size.
    binaryByteSize:
      isBinary && typeof value === 'string' ? (base64ByteLength(value) ?? undefined) : undefined,
```

And in `graphqlSpbNodeToSparkplugNode`, delete the `online: true,` line. The graph read carries
no liveness, so the field goes with it:

```ts
export function graphqlSpbNodeToSparkplugNode(node: GraphqlSpbNode): SparkplugNode {
  const { groupId, edgeNodeId, deviceId } = parseSparkplugTopic(node.topic)
  return {
    groupId,
    edgeNodeId,
    deviceId,
    topic: node.topic,
    metrics: node.metrics.map(graphqlSpbMetricToSparkplugMetric),
    sequenceNumber: node.seq,
    timestamp: node.timestamp,
  }
}
```

- [ ] **Step 6: Narrow the two types**

In `11_frontend/src/types/uns.ts`, replace the `SparkplugNode` interface (`:68`–`:77`) with the
seven-field version in this task's Produces block: `online` deleted, `sequenceNumber: number`
required because `SPBNode.seq` is non-nullable.

In `11_frontend/src/services/graphql/types.ts`, drop the two unused fields (`:123`–`:124`):

```ts
export type GraphqlSpbNode = {
  topic: string
  timestamp: string
  metrics: GraphqlSpbMetric[]
  seq: number
}
```

- [ ] **Step 7: Stop asking for the protobuf body**

In `11_frontend/src/services/graphql/queries.ts`, remove the `uuid` and `body` selections from
`GET_SPB_NODES_BY_METRIC_QUERY` so the top of the selection set reads:

```graphql
    getSpbNodesByMetric(metricNames: $metricNames) {
      topic
      timestamp
      seq
      metrics {
```

Leave the `metrics` selection exactly as it is, including both `... on SPBPrimitive` and
`... on BytesPayload` — that union is how a binary metric arrives already-encoded, and it is
what test 14 asserts against.

Add one line above the document so the reason survives:

```ts
/**
 * Decoded Sparkplug comes only from this query. `body` and `uuid` are not requested: `body`
 * is an opaque base64 blob and this console has no decoder for it, by design.
 */
```

- [ ] **Step 8: Run the whole suite to see what the type change broke**

Run: `cd 11_frontend && npx tsc --noEmit && npx vitest run`

Expected: `tsc` reports `SparkplugView.tsx:158` — `node.sequenceNumber` is no longer possibly
`undefined`, so `?? 0` is flagged only if the project enables that lint; more reliably, any
fixture in the repo that builds a `SparkplugNode` with `online` now errors. If `tsc` is clean,
that is fine too: Step 10 removes the `?? 0` regardless.

- [ ] **Step 9: Write the failing Sparkplug screen test**

Create `11_frontend/src/components/sparkplug/SparkplugView.test.tsx`. The client is mocked at
the module boundary, so no `fetch` is attempted and `src/test/setup.ts` stays quiet.

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, waitFor } from '@testing-library/react';
import { SparkplugView } from './SparkplugView';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { SparkplugNode } from '../../types/uns';

vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getSpbNodesByMetric: vi.fn() },
}));

const jumpToTopicInTree = vi.fn();

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({
    jumpToTopicInTree,
    sparkplugInitialMetric: 'Enterprise/Dept/Line/Temperature',
  }),
}));

// Exactly what getSpbNodesByMetric returns once client.ts has mapped it: one numeric metric
// and one binary metric whose value is still base64.
const NODE: SparkplugNode = {
  groupId: 'Enterprise',
  edgeNodeId: 'EdgeNode_01',
  deviceId: 'Device_A',
  topic: 'spBv1.0/Enterprise/DDATA/EdgeNode_01/Device_A',
  timestamp: '2026-09-02T06:15:00.000Z',
  sequenceNumber: 7,
  metrics: [
    {
      name: 'Enterprise/Dept/Line/Temperature',
      alias: 3,
      datatype: 'Float',
      value: 72.5,
      timestamp: '2026-09-02T06:15:00.000Z',
    },
    {
      name: 'Enterprise/Dept/Line/Waveform',
      datatype: 'Bytes',
      value: 'AAECAw==',
      timestamp: '2026-09-02T06:15:00.000Z',
      isBinary: true,
      binaryByteSize: 4,
    },
  ],
};

const mockedQuery = vi.mocked(unsGraphQLClient.getSpbNodesByMetric);

describe('SparkplugView', () => {
  beforeEach(() => {
    mockedQuery.mockReset();
    mockedQuery.mockResolvedValue([NODE]);
  });

  it('reads decoded metrics only from getSpbNodesByMetric', async () => {
    render(<SparkplugView />);

    await waitFor(() => expect(screen.getAllByTestId('spb-metric-row')).toHaveLength(2));
    expect(mockedQuery).toHaveBeenCalledTimes(1);
    expect(mockedQuery).toHaveBeenCalledWith(['Enterprise/Dept/Line/Temperature']);
    expect(screen.getByText('72.5')).toBeInTheDocument();
  });

  it('shows binary metrics as a badge with the base64 size, never as a decoded value', async () => {
    render(<SparkplugView />);

    const binary = await screen.findByTestId('spb-binary');
    expect(binary).toHaveTextContent('Binary data: 4 bytes');
    expect(screen.queryByText('AAECAw==')).toBeNull(); // only inside the hex modal, on demand
  });

  it('claims neither liveness nor a sequence it was not given', async () => {
    mockedQuery.mockResolvedValue([{ ...NODE, sequenceNumber: 0 }]);
    render(<SparkplugView />);

    const node = await screen.findByTestId('spb-node');
    expect(node).toHaveTextContent('Seq 0');
    expect(node.querySelectorAll('.animate-pulse')).toHaveLength(0);
    expect(node).not.toHaveTextContent(/online/i);
  });

  it('credits the decoding to the platform, not to the read API', async () => {
    render(<SparkplugView />);
    expect(screen.queryByText(/07_uns_graphql Sparkplug mapper/)).toBeNull();
    expect(screen.getByText(/does not decode protobuf/i)).toBeInTheDocument();
  });

  it('ships no protobuf decoder', () => {
    // Vitest runs with 11_frontend as its cwd (vitest.config.ts lives there).
    const pkg = JSON.parse(readFileSync(resolve(process.cwd(), 'package.json'), 'utf-8'));
    const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(deps.filter((d) => /protobuf|sparkplug|tahu/i.test(d))).toEqual([]);
  });
});
```

- [ ] **Step 10: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/components/sparkplug/SparkplugView.test.tsx`

Expected: FAIL — there is no `spb-metric-row`, no `spb-node`, no `spb-binary`, the byte badge
reads `[Binary Data: 4 bytes]` in different words, and the header still says
`07_uns_graphql Sparkplug mapper`. The last test (`ships no protobuf decoder`) should already
pass; if it does not, stop — something in `package.json` contradicts spec finding 7 and the plan
needs revisiting before any UI work.

- [ ] **Step 11: Fix the metric-name heuristic and the stale query**

In `11_frontend/src/components/sparkplug/SparkplugView.tsx`, replace `:41`–`:44`:

```tsx
  // Check if string looks like an ISA-95 namespace path
  const isIsa95Path = (name: string) => {
    return name.includes('/') && (name.startsWith('CovestroAG') || name.split('/').length >= 3);
  };
```

with:

```tsx
  // 05_sparkplugb maps Sparkplug to ISA-95 through the metric *name*, so a name carrying a
  // path is a namespace path. No plant name is hardcoded here.
  const isIsa95Path = (name: string) => name.includes('/');
```

Replace `:22`–`:39` — `fetchSpbData` takes the metric explicitly, and the effect resets the
search box, because `jumpToSparkplug` can fire while this screen is already mounted and
`useState`'s initialiser will not run a second time:

```tsx
  const fetchSpbData = async (query: string = metricQuery) => {
    setLoading(true);
    try {
      const metricNames = query.trim() ? [query.trim()] : [];
      const data = metricNames.length
        ? await unsGraphQLClient.getSpbNodesByMetric(metricNames)
        : [];
      setNodes(data);
    } catch (e) {
      console.error('Failed to load Sparkplug nodes', e);
    } finally {
      setLoading(false);
    }
  };

  // jumpToSparkplug sets the metric and changes the hash. If this screen is already mounted,
  // the useState initialiser above does not run again, so follow the metric explicitly.
  useEffect(() => {
    setMetricQuery(sparkplugInitialMetric);
    void fetchSpbData(sparkplugInitialMetric);
  }, [sparkplugInitialMetric]);
```

and change the initialiser at `:17` so the two agree on the empty case:

```tsx
  const [metricQuery, setMetricQuery] = useState(sparkplugInitialMetric);
```

- [ ] **Step 12: Fix the header, the badge and the binary value**

Replace the subtitle at `:92`–`:94`:

```tsx
              <p className="text-[10px] text-[#64748B] font-mono">
                Sparkplug B is decoded on ingest by the platform and stored in the graph. This
                screen reads those metrics through getSpbNodesByMetric and does not decode
                protobuf.
              </p>
```

Replace the notice at `:98`–`:102` with plain words — the claim is true (`05_sparkplugb`'s
README: *"will not be publishing any control messages"*), so it stays, minus the shorthand:

```tsx
          {/* True of the platform, not just of this screen — 05_sparkplugb publishes no commands */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-purple-950/30 border border-purple-800/40 text-[10px] text-purple-300">
            <Shield className="w-3.5 h-3.5 text-purple-400 shrink-0" />
            <span>Read-only. This console sends no Sparkplug commands.</span>
          </div>
```

Replace the binary branch of `renderMetricValue` (`:47`–`:64`) so an unknown size renders as an
unknown size:

```tsx
  const renderMetricValue = (metric: SparkplugMetric) => {
    if (metric.isBinary || metric.datatype === 'Bytes' || metric.datatype === 'File') {
      return (
        <div className="flex items-center gap-2">
          <span
            data-testid="spb-binary"
            className="px-2 py-0.5 rounded bg-purple-950/80 border border-purple-800/80 text-purple-300 font-mono text-[10px] flex items-center gap-1"
          >
            <Binary className="w-3 h-3 text-purple-400" />
            <span>
              {metric.binaryByteSize === undefined
                ? 'Binary data'
                : `Binary data: ${metric.binaryByteSize} bytes`}
            </span>
          </span>
          <button
            type="button"
            onClick={() => setSelectedBinaryMetric(metric)}
            className="text-[10px] text-[#FFC107] hover:underline font-mono cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            Show base64
          </button>
        </div>
      );
    }
```

Leave the boolean, number and fallback branches below it untouched.

- [ ] **Step 13: Replace the green dot with the timestamp the node actually carries**

`SPBNode.timestamp` is real — `type/sparkplugb_node.py:307` describes it as when the node was
last modified, and it arrives on every payload. Replace `:150`–`:160`:

```tsx
                <div className="flex items-center gap-3">
                  <span className="font-bold text-[#F8FAFC] text-xs">
                    {node.groupId} / {node.edgeNodeId} {node.deviceId ? `• ${node.deviceId}` : ''}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B] text-[#94A3B8] text-[9px]">
                    Seq {node.sequenceNumber}
                  </span>
                  <span className="text-[9px] text-[#64748B]">
                    Payload timestamp {new Date(node.timestamp).toLocaleString()}
                  </span>
                </div>
```

Add the test id to the node wrapper at `:144`–`:147` and the metric row at `:187`, and give the
search input and the empty state theirs:

```tsx
            <div
              key={`${node.groupId}-${node.edgeNodeId}-${node.deviceId || ''}`}
              data-testid="spb-node"
              className="bg-[#111114] border border-[#1E293B] rounded-lg overflow-hidden shadow-lg"
            >
```

```tsx
                        <tr key={mIdx} data-testid="spb-metric-row" className="hover:bg-[#1E293B]/40 transition-colors">
```

```tsx
              placeholder="Search by metric name, ISA-95 path, or alias..."
              aria-label="Search Sparkplug metrics"
              data-testid="spb-search"
```

```tsx
          <div data-testid="spb-empty" className="text-center py-16 bg-[#111114] border border-[#1E293B] rounded-lg text-[#64748B]">
            <Info className="w-8 h-8 mx-auto mb-2 text-[#64748B]" />
            <p>No Sparkplug B nodes or metrics matched the query.</p>
          </div>
```

Finally, the modal footnote at `:287`–`:289` — say what is true instead of reassuring:

```tsx
            <div className="text-[10px] text-[#64748B]">
              Base64 as it arrived from GraphQL. Nothing in this console decodes it.
            </div>
```

and its heading at `:268` becomes `Binary metric, base64` rather than
`Binary Payload Inspector`, because no inspection happens.

- [ ] **Step 14: Run the Sparkplug screen test**

Run: `cd 11_frontend && npx vitest run src/components/sparkplug/SparkplugView.test.tsx`

Expected: PASS, five tests.

- [ ] **Step 15: Write the failing feed-routing test**

Here is the eighth finding, and it is the one that decides whether spec test 14's first half means
anything. `UNSContext.tsx:364`–`:366`:

```tsx
    const unsubscribe = unsGraphQLClient.subscribeMqttMessages(effectiveTopics, (msg) => {
      if (isPausedRef.current || isSparkplugTopic(msg.topic)) {
        return;
      }
```

The subscription asks for `['#']` by default (`:352`), and
`07_uns_graphql/src/uns_graphql/type/mqtt_event.py:62`–`:64` returns a `BytesPayload` for any
topic under the Sparkplug namespace. So live Sparkplug *does* arrive — and this line throws it
away before it reaches `mqttFeed`. The `SPB` badge in `LiveMqttFeed.tsx:143`–`:147` and the
`isSpb` check at `:114` can never fire in the running console. Spec test 14 asserts a badge that
today is unreachable code, and a test that mocks `useUNS` would happily "prove" it.

The early return is doing two jobs, and only one of them is right. Everything after the
`setMqttFeed` call patches the ISA-95 tree — `setRootNodes:377`, `setNodeChildrenMap:381`,
`setSelectedNode:383` — and the global constraint *"Sparkplug `spBv1.0/` never enters the ISA-95
tree"* means Sparkplug must keep being excluded from those three. It says nothing about the feed.
An integrator watching raw broker traffic needs to see that `spBv1.0/` messages are arriving; that
is the whole point of a live feed. Split the guard.

Create `11_frontend/src/context/UNSContext.feed.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { UNSProvider, useUNS } from './UNSContext';
import { unsGraphQLClient } from '../services/graphql/client';
import type { MqttMessage, SystemHealthInfo } from '../types/uns';

// Every client method UNSProvider touches while mounting. getHealth returns an empty object
// on purpose: nothing this test renders reads a health field, and an empty object keeps the
// test from breaking when SystemHealthInfo gains keys (it does, in Task 19).
vi.mock('../services/graphql/client', () => ({
  unsGraphQLClient: {
    getHealth: vi.fn(() => ({}) as SystemHealthInfo),
    setUrls: vi.fn(),
    onHealthChange: vi.fn(() => () => {}),
    getUnsRootNodes: vi.fn(async () => [
      {
        name: 'Enterprise',
        topic: 'Enterprise',
        namespace: 'Enterprise',
        hasChildren: true,
        payload: { value: 1 },
        lastUpdated: '2026-09-02T06:00:00.000Z',
      },
    ]),
    getUnsNodeChildren: vi.fn(async () => []),
    getUnsNodes: vi.fn(async () => []),
    getTopicEnrichment: vi.fn(async () => null),
    getHistoricEvents: vi.fn(async () => []),
    subscribeMqttMessages: vi.fn(() => () => {}),
  },
}));

/** Reads back exactly what the feed and the tree ended up holding. */
const Probe: React.FC = () => {
  const { mqttFeed, rootNodes } = useUNS();
  return (
    <div>
      <span data-testid="feed-topics">{mqttFeed.map((m) => m.topic).join(',')}</span>
      <span data-testid="root-payload">{JSON.stringify(rootNodes[0]?.payload ?? null)}</span>
    </div>
  );
};

const subscribe = vi.mocked(unsGraphQLClient.subscribeMqttMessages);

/** The callback UNSProvider handed to subscribeMqttMessages on its last effect run. */
function emit(message: MqttMessage) {
  const handler = subscribe.mock.calls.at(-1)?.[1];
  if (!handler) throw new Error('UNSProvider never subscribed');
  act(() => handler(message));
}

describe('UNSContext MQTT routing', () => {
  beforeEach(() => {
    subscribe.mockClear();
    localStorage.clear();
  });

  it('puts live Sparkplug in the feed, base64 payload and all', async () => {
    render(
      <UNSProvider>
        <Probe />
      </UNSProvider>,
    );
    await screen.findByTestId('feed-topics');

    emit({
      id: 'spb-1',
      topic: 'spBv1.0/Enterprise/DDATA/EdgeNode_01',
      payload: 'AAECAw==',
      timestamp: '2026-09-02T06:15:00.000Z',
      isSparkplug: true,
    });

    expect(screen.getByTestId('feed-topics')).toHaveTextContent(
      'spBv1.0/Enterprise/DDATA/EdgeNode_01',
    );
  });

  it('never lets a Sparkplug payload patch an ISA-95 node', async () => {
    render(
      <UNSProvider>
        <Probe />
      </UNSProvider>,
    );
    await screen.findByText('{"value":1}');

    // A Sparkplug topic that collides with a tree topic must still not overwrite it.
    emit({
      id: 'spb-2',
      topic: 'Enterprise',
      payload: { value: 2 },
      timestamp: '2026-09-02T06:16:00.000Z',
      isSparkplug: true,
    });
    expect(screen.getByTestId('root-payload')).toHaveTextContent('{"value":2}');

    emit({
      id: 'spb-3',
      topic: 'spBv1.0/Enterprise',
      payload: { value: 99 },
      timestamp: '2026-09-02T06:17:00.000Z',
    });
    expect(screen.getByTestId('root-payload')).toHaveTextContent('{"value":2}');
  });

  it('drops everything while the feed is paused', async () => {
    render(
      <UNSProvider>
        <Probe />
      </UNSProvider>,
    );
    await screen.findByTestId('feed-topics');

    // setIsFeedPaused is not reachable from the Probe, so assert the un-paused default
    // instead: an ISA-95 message lands in the feed too. Pausing is covered by Task 13.
    emit({
      id: 'uns-1',
      topic: 'Enterprise/Line/temperature',
      payload: { value: 21 },
      timestamp: '2026-09-02T06:18:00.000Z',
    });
    expect(screen.getByTestId('feed-topics')).toHaveTextContent('Enterprise/Line/temperature');
  });
});
```

The second test is the important one. It uses a Sparkplug-flagged message on a *non*-Sparkplug
topic to prove the tree guard keys off the topic namespace and not off `isSparkplug`, then a real
`spBv1.0/` topic to prove the tree is left alone.

- [ ] **Step 16: Run it and watch the first test fail**

Run: `cd 11_frontend && npx vitest run src/context/UNSContext.feed.test.tsx`

Expected: test 1 FAILS — `feed-topics` is empty, because the Sparkplug message was discarded.
Tests 2 and 3 pass already; they are the regression net for the next step.

- [ ] **Step 17: Split the guard**

In `11_frontend/src/context/UNSContext.tsx`, replace `:364`–`:374`:

```tsx
    const unsubscribe = unsGraphQLClient.subscribeMqttMessages(effectiveTopics, (msg) => {
      if (isPausedRef.current) {
        return;
      }

      setMqttFeed((prev) => {
        const next = [msg, ...prev];
        const cap = maxBufferRef.current || 500;
        return next.length > cap ? next.slice(0, cap) : next;
      });

      // Everything below patches the ISA-95 tree, and spBv1.0/ is a separate namespace: a
      // Sparkplug message is broker traffic an integrator should see in the feed, never a
      // value on a UNS Node. Decoded Sparkplug lives on its own screen.
      if (isSparkplugTopic(msg.topic)) {
        return;
      }
```

Leave the three patch calls below it exactly as they are.

- [ ] **Step 18: Run it again**

Run: `cd 11_frontend && npx vitest run src/context/UNSContext.feed.test.tsx`

Expected: PASS, three tests.

- [ ] **Step 19: Write the live-feed rendering test**

Step 17 made live Sparkplug reachable; this asserts what it looks like when it arrives.
`map-nodes.ts:59`–`:61` stores a `BytesPayload` as its base64 string, so the row renders bytes and
a badge — never a metric name, which could only come from a browser-side decode.

Create `11_frontend/src/components/home/LiveMqttFeed.sparkplug.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LiveMqttFeed } from './LiveMqttFeed';
import type { MqttMessage } from '../../types/uns';

const SPB_MESSAGE: MqttMessage = {
  id: 'spBv1.0/Enterprise/DDATA/EdgeNode_01/Device_A:1',
  topic: 'spBv1.0/Enterprise/DDATA/EdgeNode_01/Device_A',
  payload: 'AAECAw==',
  timestamp: '2026-09-02T06:15:00.000Z',
  isSparkplug: true,
};

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({
    mqttFeed: [SPB_MESSAGE],
    isFeedPaused: false,
    setIsFeedPaused: vi.fn(),
    feedTopicFilter: '',
    setFeedTopicFilter: vi.fn(),
    clearMqttFeed: vi.fn(),
    followSelection: false,
    setFollowSelection: vi.fn(),
    selectedNode: null,
    jumpToTopicInTree: vi.fn(),
    settings: { maxFeedBuffer: 200 },
  }),
}));

describe('LiveMqttFeed with Sparkplug', () => {
  it('badges live Sparkplug and shows the bytes it received, not decoded metrics', () => {
    render(<LiveMqttFeed />);

    expect(screen.getByText('SPB')).toBeInTheDocument();
    expect(screen.getByText(SPB_MESSAGE.topic)).toBeInTheDocument();
    expect(screen.getByText('AAECAw==')).toBeInTheDocument();
    // A decoded metric name could only come from a browser-side protobuf decode.
    expect(screen.queryByText(/Temperature/i)).toBeNull();
  });
});
```

- [ ] **Step 20: Run it**

Run: `cd 11_frontend && npx vitest run src/components/home/LiveMqttFeed.sparkplug.test.tsx`

Expected: PASS on the first run. The rendering half of this screen was already correct — the test
exists so it stays that way once Step 17 has made it reachable. If it fails on `SPB`, check that
`settings` in the mock carries every field `LiveMqttFeed` destructures.

- [ ] **Step 21: Fix the same misattribution in PayloadInspector**

In `11_frontend/src/components/home/PayloadInspector.tsx`, replace the two lines of copy inside
the Sparkplug panel (`:262`–`:266`):

```tsx
                <span className="text-purple-900 dark:text-[#A855F7] font-semibold text-[11px]">Sparkplug B topic</span>
                <p className="text-[10px] text-purple-700 dark:text-[#94A3B8]">
                  Published as protobuf and decoded by the platform on ingest. Open Sparkplug to
                  read the decoded metrics.
                </p>
```

Leave the `Open in Sparkplug` button and its `jumpToSparkplug(selectedNode.name)` call as they
are — Step 11 makes that jump work a second time.

- [ ] **Step 22: Type-check and run everything**

```bash
cd 11_frontend
npx tsc --noEmit
npx vitest run
```

Expected: clean, all green. If `tsc` complains about an unused `SparkplugMetric` import in
`SparkplugView.tsx`, it is still used by `renderMetricValue`'s parameter — the error is more
likely `SparkplugNode` in the test fixture missing a field you kept. `isSparkplugTopic` is still
imported and used in `UNSContext.tsx` after Step 17; do not remove the import.

- [ ] **Step 23: Commit**

```bash
cd 11_frontend
git add src/lib/uns/base64.ts src/lib/uns/base64.test.ts src/lib/uns/map-nodes.ts \
        src/types/uns.ts src/services/graphql/queries.ts src/services/graphql/types.ts \
        src/context/UNSContext.tsx src/context/UNSContext.feed.test.tsx \
        src/components/sparkplug/SparkplugView.tsx \
        src/components/sparkplug/SparkplugView.test.tsx \
        src/components/home/PayloadInspector.tsx \
        src/components/home/LiveMqttFeed.sparkplug.test.tsx
git commit -m "fix(frontend): keep Sparkplug honest — no decoding, no invented sizes

Live Sparkplug reaches the feed now. UNSContext discarded every spBv1.0/
message before it got there, which made the SPB badge unreachable code; the
guard is split so Sparkplug shows up as broker traffic and still never
patches an ISA-95 node.

Decoded metrics come only from getSpbNodesByMetric, and the screen now says
where decoding happens: on ingest, in the platform, not in 07_uns_graphql and
not in the browser. Byte counts come from base64ByteLength instead of
halving a base64 string, and an unknown size prints no number. The hardcoded
online:true and its green dot are gone — a graph read carries no liveness —
along with the CovestroAG heuristic and the seq 0 default. uuid and body are
no longer requested: body is an opaque blob this console must not decode.
Jumping to a second metric now re-queries instead of showing the first."
```

**Definition of done:**
- A live `spBv1.0/` message appears in the MQTT feed with its base64 payload and an `SPB` badge,
  asserted by test.
- No `spBv1.0/` message ever patches a UNS Node's payload, asserted by test.
- `getSpbNodesByMetric` is the only source of decoded Sparkplug values, asserted by test.
- `package.json` contains no protobuf, sparkplug or tahu dependency, asserted by test.
- `[Binary Data: 32 bytes]` cannot be produced: a size is printed only when
  `base64ByteLength` returned one, and `Binary data` alone otherwise.
- `SparkplugNode.online` does not exist; `grep -n "online" 11_frontend/src/types/uns.ts` is
  empty, and no node header pulses.
- `sequenceNumber` is required and rendered as given — no `?? 0`.
- `CovestroAG` appears nowhere in `SparkplugView.tsx`.
- `07_uns_graphql Sparkplug mapper` appears nowhere in `11_frontend/src`.
- `uuid` and `body` are absent from `GET_SPB_NODES_BY_METRIC_QUERY` and `GraphqlSpbNode`.
- Opening a Sparkplug node, returning, and opening a different one queries the second metric.
- `npx tsc --noEmit` clean; `npx vitest run` green.

---

## Task 23: ALARMS — evaluate every message in the feed, not only the newest one

Spec section 8 says the console evaluates Alert Rules in the browser, and ADR-0005 accepted that.
Neither says it may skip readings. It does.

`AlarmContext.tsx`'s evaluation effect (`:639`–`:751` before Task 20 edits it) opens:

```tsx
  useEffect(() => {
    if (mqttFeed.length === 0) return;
    const latestMessage = mqttFeed[0];
```

`mqttFeed` is newest-first (`UNSContext.tsx:370`, `[msg, ...prev]`), so this evaluates exactly one
reading per effect run and drops every other message that arrived in the same React commit.

**Why that loses breaches, with numbers from this repo.** `99_simulator` publishes on an interval
per topic, and the default subscription is `['#']` — every topic in the plant, into one feed.
React batches state updates, so a commit that lands three messages evaluates one and discards two.
The two discarded ones are not "nearly the same reading": with `['#']` they are usually *different
topics*, so a rule watching topic B never sees B's message at all when A and C arrive in the same
batch. The faster the plant publishes, the more rules go quiet — which is the worst possible
failure direction for an alarm system, because nothing on screen changes when it happens. The
`No Active Incidents` panel Task 20 rewords is reassuring precisely when this bug is at its worst.

**Two more defects in the same effect, both of which get worse once the loop is fixed:**

1. **Side effects run inside a state updater.** `playAlarmChime`, `setRules`, `reportEvaluation`
   and `logAlarmAudit` are all called from inside the `setActiveAlarms((prev) => …)` callback
   (`:700`–`:724`). React may invoke an updater more than once, and `src/main.tsx` wraps the app in
   `<StrictMode>`, which does exactly that in development. So today a single breach increments
   `triggerCount` twice, writes two audit entries, POSTs two evaluations and plays the chime twice
   in `npm run dev`. Evaluating a whole batch multiplies that. An updater has to be pure.
2. **Order inside a batch is unspecified.** Once several messages are evaluated per run, a value
   that breached and then recovered inside one batch must end on the recovery, or an
   `autoResolveOnNormal` rule latches an alarm that the plant has already cleared. That means
   oldest-first, and it means the decision for message *n+1* has to see the alarms message *n*
   produced — which a `setActiveAlarms` call cannot provide, because the state has not committed
   yet.

All three point the same way: make the decision a pure function over
`(messages, rules, alarms)`, let it fold a batch, and let the context perform the side effects it
returns. That is also the only shape in which "a burst of three messages raises one alarm" is
testable without a broker.

**Ordering with the rest of this plan.** This task runs **after Task 20**, which deletes
`INITIAL_RULES`, `INITIAL_ACTIVE_ALARMS`, `INITIAL_ALARM_AUDIT` and `restoreDefaultRules`, and
replaces the inline topic matcher with `topicMatchesFilter` from `src/lib/uns/topic-match.ts`
(Task 14). Line numbers in this task refer to the file **as Task 20 leaves it**, so locate the code
by name. The topic matcher is not re-litigated here: the evaluator calls
`topicMatchesFilter(rule.topic, message.topic)` and nothing else.

**What does not change.** Every observable decision keeps today's rule, so that a reviewer can
check this task by reading the diff rather than the plant:

- A breach with no live alarm for that rule raises one, `ACTIVE_UNACK`.
- A breach with a live alarm (`ACTIVE_UNACK` or `ACTIVE_ACK`) updates `currentValue` and
  `conditionDescription` only — no second alarm, no second audit entry, no chime, and **no**
  `recordAlertRuleEvaluation(id, true)`, because today's `reportEvaluation(rule.id, true)` sits in
  the new-alarm branch.
- A non-breach reports a quiet evaluation, and resolves a live alarm only when
  `autoResolveOnNormal` is set.
- The metric is read as `payload[rule.metricField] ?? payload.value ?? payload[lowercased]`, and a
  message whose payload is not an object is skipped entirely.
- `delaySeconds` is still ignored, and escalation still never fires. Both are Task 24; naming them
  here so nobody reads this task's tests as proof that they work.

**Files:**
- Create: `11_frontend/src/lib/alarms/evaluate.ts`
- Modify: `11_frontend/src/context/AlarmContext.tsx` — the `evaluateCondition` helper and the
  evaluation `useEffect` are replaced, `testTriggerRule` follows the rename and loses its invented
  fallback topic, and `activeAlarmsRef` and `lastEvaluatedIdRef` are added
- Test: `11_frontend/src/lib/alarms/evaluate.test.ts` (create)
- Test: `11_frontend/src/context/AlarmContext.evaluation.test.tsx` (create)

`AlarmContext.test.tsx` from Task 20 is left alone. It owns seeding, the hand-over to the platform
and the topic matcher; this task's file owns feed coverage. Two focused files beat one that fails
for six unrelated reasons.

**Interfaces:**
- Consumes: `topicMatchesFilter(filter: string, topic: string): boolean` from
  `src/lib/uns/topic-match.ts` (Task 14); `unsGraphQLClient.recordAlertRuleEvaluation(ruleId, triggered)`
  (already in the repo, unchanged); `AlertRule`, `ActiveAlarm` from `src/types/alarm.ts`;
  `MqttMessage` from `src/types/uns.ts`.
- Produces, in `src/lib/alarms/evaluate.ts`:
  ```ts
  /** What one rule decided about one message. The context turns these into side effects. */
  export type AlarmOutcome =
    | { kind: 'TRIGGERED'; rule: AlertRule; alarm: ActiveAlarm; description: string }
    | { kind: 'UPDATED'; rule: AlertRule; alarm: ActiveAlarm; description: string }
    | { kind: 'CLEARED'; rule: AlertRule; alarm: ActiveAlarm; value: unknown }
    | { kind: 'QUIET'; rule: AlertRule };

  export interface AlarmEvaluation {
    /** The same array reference when no rule changed anything. */
    alarms: ActiveAlarm[];
    outcomes: AlarmOutcome[];
  }

  /** Injected so a test can assert on ids and timestamps instead of guessing them. */
  export interface AlarmClock {
    now: () => string;
    newAlarmId: () => string;
  }

  export function conditionResult(
    rule: AlertRule,
    value: unknown,
  ): { breached: boolean; description: string };

  /** `messages` must be oldest-first. */
  export function evaluateFeed(
    messages: MqttMessage[],
    rules: AlertRule[],
    alarms: ActiveAlarm[],
    clock: AlarmClock,
  ): AlarmEvaluation;
  ```
  No change to `AlarmContextType`. Nothing outside `AlarmContext.tsx` imports this module.

- [ ] **Step 1: Write the failing evaluator test**

Create `11_frontend/src/lib/alarms/evaluate.test.ts`. The clock is a counter, so every assertion
names an exact id.

```ts
import { describe, expect, it } from 'vitest';
import { conditionResult, evaluateFeed } from './evaluate';
import type { ActiveAlarm, AlertRule } from '../../types/alarm';
import type { MqttMessage } from '../../types/uns';

const LINE = 'CovestroAG/Dormagen/Production/Line1';

function clock() {
  let n = 0;
  return {
    now: () => '2026-09-02T10:00:00.000Z',
    newAlarmId: () => `alm-${(n += 1)}`,
  };
}

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r-temp',
    name: 'Line 1 temperature high',
    description: '',
    enabled: true,
    severity: 'HIGH',
    category: 'TEMPERATURE',
    topic: `${LINE}/#`,
    metricField: 'temp',
    condition: 'GREATER_THAN',
    thresholdValue: 80,
    unit: '°C',
    targetRoles: ['operator'],
    autoResolveOnNormal: false,
    actions: { inAppNotification: true, audioChime: false, mqttPublishOnTrigger: false, emailWebhook: false },
    triggerCount: 0,
    createdAt: '2026-09-01T00:00:00.000Z',
    updatedAt: '2026-09-01T00:00:00.000Z',
    ...overrides,
  };
}

function message(id: string, topic: string, payload: MqttMessage['payload']): MqttMessage {
  return { id, topic, payload, timestamp: '2026-09-02T10:00:00.000Z' };
}

describe('conditionResult', () => {
  it('reads the threshold the way the rule was written', () => {
    expect(conditionResult(rule(), 91).breached).toBe(true);
    expect(conditionResult(rule(), 80).breached).toBe(false);
    expect(conditionResult(rule({ condition: 'LESS_THAN' }), 12).breached).toBe(true);
    expect(conditionResult(rule({ condition: 'EQUALS', thresholdValue: 'FAULT' }), 'fault').breached).toBe(true);
    expect(
      conditionResult(rule({ condition: 'RANGE_OUTSIDE', thresholdValue: 10, thresholdUpperValue: 20 }), 25).breached,
    ).toBe(true);
    expect(conditionResult(rule({ condition: 'CONTAINS', thresholdValue: 'trip' }), 'RELIEF TRIP').breached).toBe(true);
  });

  it('treats a missing value as not breached, never as zero', () => {
    expect(conditionResult(rule(), null).breached).toBe(false);
    expect(conditionResult(rule(), undefined).breached).toBe(false);
    expect(conditionResult(rule({ condition: 'LESS_THAN' }), null).breached).toBe(false);
  });

  it('describes the comparison in the rule’s own unit', () => {
    expect(conditionResult(rule(), 91).description).toBe('temp (91 °C) > 80 °C');
  });
});

describe('evaluateFeed', () => {
  it('sees a breach that is not the newest message in the batch', () => {
    const messages = [
      message('m1', `${LINE}/Cell1`, { temp: 60 }),
      message('m2', `${LINE}/Cell1`, { temp: 91 }), // the one today's code drops
      message('m3', `${LINE}/Cell2`, { other: 1 }),
    ];

    const { alarms, outcomes } = evaluateFeed(messages, [rule()], [], clock());

    expect(alarms).toHaveLength(1);
    expect(alarms[0]).toMatchObject({
      id: 'alm-1',
      ruleId: 'r-temp',
      topic: `${LINE}/Cell1`,
      status: 'ACTIVE_UNACK',
      currentValue: 91,
      triggeredAt: '2026-09-02T10:00:00.000Z',
    });
    expect(outcomes.filter((o) => o.kind === 'TRIGGERED')).toHaveLength(1);
  });

  it('raises one alarm per rule for a burst, and keeps the last value', () => {
    const messages = [
      message('m1', `${LINE}/Cell1`, { temp: 91 }),
      message('m2', `${LINE}/Cell1`, { temp: 96 }),
      message('m3', `${LINE}/Cell1`, { temp: 99 }),
    ];

    const { alarms, outcomes } = evaluateFeed(messages, [rule()], [], clock());

    expect(alarms).toHaveLength(1);
    expect(alarms[0].currentValue).toBe(99);
    expect(outcomes.filter((o) => o.kind === 'TRIGGERED')).toHaveLength(1);
    expect(outcomes.filter((o) => o.kind === 'UPDATED')).toHaveLength(2);
  });

  it('ends on the recovery when a value breaches and recovers inside one batch', () => {
    const messages = [
      message('m1', `${LINE}/Cell1`, { temp: 91 }),
      message('m2', `${LINE}/Cell1`, { temp: 64 }),
    ];

    const { alarms, outcomes } = evaluateFeed(
      messages,
      [rule({ autoResolveOnNormal: true })],
      [],
      clock(),
    );

    expect(alarms).toHaveLength(1);
    expect(alarms[0].status).toBe('RESOLVED');
    expect(alarms[0].clearedAt).toBe('2026-09-02T10:00:00.000Z');
    expect(outcomes.map((o) => o.kind)).toEqual(['TRIGGERED', 'QUIET', 'CLEARED']);
  });

  it('leaves a live alarm alone when the rule does not auto-resolve', () => {
    const live: ActiveAlarm = {
      id: 'alm-existing',
      ruleId: 'r-temp',
      ruleName: 'Line 1 temperature high',
      topic: `${LINE}/Cell1`,
      severity: 'HIGH',
      category: 'TEMPERATURE',
      conditionDescription: 'temp (91 °C) > 80 °C',
      currentValue: 91,
      status: 'ACTIVE_ACK',
      triggeredAt: '2026-09-02T09:00:00.000Z',
      targetRoles: ['operator'],
    };

    const { alarms, outcomes } = evaluateFeed(
      [message('m1', `${LINE}/Cell1`, { temp: 64 })],
      [rule()],
      [live],
      clock(),
    );

    expect(alarms).toEqual([live]);
    expect(outcomes).toEqual([{ kind: 'QUIET', rule: rule() }]);
  });

  it('returns the same array when nothing changed, so the context does not set state', () => {
    const alarms: ActiveAlarm[] = [];
    const result = evaluateFeed([message('m1', 'Other/Line', { temp: 91 })], [rule()], alarms, clock());

    expect(result.alarms).toBe(alarms);
    expect(result.outcomes).toEqual([]);
  });

  it('ignores disabled rules and non-object payloads', () => {
    const disabled = evaluateFeed(
      [message('m1', `${LINE}/Cell1`, { temp: 91 })],
      [rule({ enabled: false })],
      [],
      clock(),
    );
    expect(disabled.alarms).toHaveLength(0);
    expect(disabled.outcomes).toEqual([]);

    const bytes = evaluateFeed([message('m2', `${LINE}/Cell1`, 'AAECAw==')], [rule()], [], clock());
    expect(bytes.outcomes).toEqual([]);
  });

  it('falls back to a payload `value` key when the rule names no field it can find', () => {
    const { alarms } = evaluateFeed(
      [message('m1', `${LINE}/Cell1`, { value: 91 })],
      [rule()],
      [],
      clock(),
    );
    expect(alarms).toHaveLength(1);
  });

  it('reports a quiet evaluation once per matching message, per rule', () => {
    const { outcomes } = evaluateFeed(
      [
        message('m1', `${LINE}/Cell1`, { temp: 60 }),
        message('m2', `${LINE}/Cell1`, { temp: 61 }),
      ],
      [rule()],
      [],
      clock(),
    );
    expect(outcomes.filter((o) => o.kind === 'QUIET')).toHaveLength(2);
  });
});
```

Two of these tests carry the contract the context depends on and are easy to weaken by accident:
`returns the same array when nothing changed` asserts reference identity with `toBe`, which is what
lets the effect skip `setActiveAlarms`; and `leaves a live alarm alone when the rule does not
auto-resolve` asserts on `outcomes` rather than on state, because a `QUIET` outcome with no
`CLEARED` beside it is the whole behaviour.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/lib/alarms/evaluate.test.ts`

Expected: FAIL — `Failed to resolve import "./evaluate"`.

- [ ] **Step 3: Write the evaluator**

Create `11_frontend/src/lib/alarms/evaluate.ts`. `conditionResult` is `evaluateCondition` moved out
of `AlarmContext.tsx` unchanged except for its name and the `desc` → `description` field, so the
comparison semantics an operator already relies on do not shift underneath them.

```ts
/**
 * Alert Rule evaluation, as a fold over the messages the console has seen.
 *
 * ADR-0005 put evaluation in the browser. That is only defensible if it evaluates every
 * reading it received, and if the decision is a pure function — the version that lived inside
 * a setActiveAlarms updater fired its side effects twice under StrictMode and could only ever
 * see one message per commit.
 *
 * Nothing here reaches for a clock or a random number: both arrive as `clock`, so a test can
 * name the ids and timestamps it expects.
 */

import type { ActiveAlarm, AlertRule } from '../../types/alarm'
import type { MqttMessage } from '../../types/uns'
import { topicMatchesFilter } from '../uns/topic-match'

export type AlarmOutcome =
  | { kind: 'TRIGGERED'; rule: AlertRule; alarm: ActiveAlarm; description: string }
  | { kind: 'UPDATED'; rule: AlertRule; alarm: ActiveAlarm; description: string }
  | { kind: 'CLEARED'; rule: AlertRule; alarm: ActiveAlarm; value: unknown }
  | { kind: 'QUIET'; rule: AlertRule }

export interface AlarmEvaluation {
  alarms: ActiveAlarm[]
  outcomes: AlarmOutcome[]
}

export interface AlarmClock {
  now: () => string
  newAlarmId: () => string
}

function withUnit(rule: AlertRule, value: unknown): string {
  return rule.unit ? `${value} ${rule.unit}` : `${value}`
}

/** True when `value` breaches `rule`, plus the sentence an operator reads on the alarm row. */
export function conditionResult(
  rule: AlertRule,
  value: unknown,
): { breached: boolean; description: string } {
  if (value === undefined || value === null) {
    return { breached: false, description: 'Value is null/undefined' }
  }

  const numVal = typeof value === 'number' ? value : parseFloat(String(value))
  const numThresh =
    typeof rule.thresholdValue === 'number' ? rule.thresholdValue : parseFloat(String(rule.thresholdValue))
  const comparable = !isNaN(numVal) && !isNaN(numThresh)

  switch (rule.condition) {
    case 'GREATER_THAN':
      return {
        breached: comparable && numVal > numThresh,
        description: `${rule.metricField} (${withUnit(rule, value)}) > ${withUnit(rule, rule.thresholdValue)}`,
      }
    case 'LESS_THAN':
      return {
        breached: comparable && numVal < numThresh,
        description: `${rule.metricField} (${withUnit(rule, value)}) < ${withUnit(rule, rule.thresholdValue)}`,
      }
    case 'EQUALS':
      return {
        breached: String(value).toLowerCase() === String(rule.thresholdValue).toLowerCase(),
        description: `${rule.metricField} (${value}) == ${rule.thresholdValue}`,
      }
    case 'NOT_EQUALS':
      return {
        breached: String(value).toLowerCase() !== String(rule.thresholdValue).toLowerCase(),
        description: `${rule.metricField} (${value}) != ${rule.thresholdValue}`,
      }
    case 'RANGE_OUTSIDE': {
      const upper = rule.thresholdUpperValue ?? numThresh
      return {
        breached: !isNaN(numVal) && (numVal < numThresh || numVal > upper),
        description: `${rule.metricField} (${value}) outside [${numThresh}, ${upper}]${
          rule.unit ? ' ' + rule.unit : ''
        }`,
      }
    }
    case 'CONTAINS':
      return {
        breached: String(value).toLowerCase().includes(String(rule.thresholdValue).toLowerCase()),
        description: `${rule.metricField} contains "${rule.thresholdValue}"`,
      }
    default:
      // STALE_TIMEOUT needs a clock the feed does not carry. It is configurable and inert;
      // Task 24 is where the editor stops offering it.
      return { breached: false, description: '' }
  }
}

/** The alarm this rule already has on screen, if any. */
function liveAlarm(alarms: ActiveAlarm[], ruleId: string): ActiveAlarm | undefined {
  return alarms.find(
    (a) => a.ruleId === ruleId && (a.status === 'ACTIVE_UNACK' || a.status === 'ACTIVE_ACK'),
  )
}

/**
 * Fold `messages` — oldest first — over `rules` and `alarms`.
 *
 * Oldest first matters: a value that breached and recovered inside one batch has to end on
 * the recovery, or an autoResolveOnNormal rule latches an alarm the plant already cleared.
 * `alarms` is returned by reference when no rule changed anything, so the caller can skip
 * setState entirely.
 */
export function evaluateFeed(
  messages: MqttMessage[],
  rules: AlertRule[],
  alarms: ActiveAlarm[],
  clock: AlarmClock,
): AlarmEvaluation {
  let next = alarms
  const outcomes: AlarmOutcome[] = []

  for (const message of messages) {
    if (!message.payload || typeof message.payload !== 'object') continue
    const payload = message.payload as Record<string, unknown>

    for (const rule of rules) {
      if (!rule.enabled) continue
      if (!topicMatchesFilter(rule.topic, message.topic)) continue

      const value =
        payload[rule.metricField] ?? payload['value'] ?? payload[rule.metricField.toLowerCase()]
      if (value === undefined) continue

      const { breached, description } = conditionResult(rule, value)
      const existing = liveAlarm(next, rule.id)

      if (breached && existing) {
        const updated: ActiveAlarm = { ...existing, currentValue: value, conditionDescription: description }
        next = next.map((a) => (a.id === existing.id ? updated : a))
        outcomes.push({ kind: 'UPDATED', rule, alarm: updated, description })
        continue
      }

      if (breached) {
        const alarm: ActiveAlarm = {
          id: clock.newAlarmId(),
          ruleId: rule.id,
          ruleName: rule.name,
          topic: message.topic,
          severity: rule.severity,
          category: rule.category,
          conditionDescription: description,
          currentValue: value,
          unit: rule.unit,
          status: 'ACTIVE_UNACK',
          triggeredAt: clock.now(),
          targetRoles: rule.targetRoles,
          escalated: false,
        }
        next = [alarm, ...next]
        outcomes.push({ kind: 'TRIGGERED', rule, alarm, description })
        continue
      }

      // A quiet evaluation is still an evaluation: it is what tells the platform this rule is
      // being applied at all. Throttling belongs to the caller, not here.
      outcomes.push({ kind: 'QUIET', rule })

      if (existing && rule.autoResolveOnNormal) {
        const resolved: ActiveAlarm = {
          ...existing,
          status: 'RESOLVED',
          clearedAt: clock.now(),
          currentValue: value,
        }
        next = next.map((a) => (a.id === existing.id ? resolved : a))
        outcomes.push({ kind: 'CLEARED', rule, alarm: resolved, value })
      }
    }
  }

  return { alarms: next, outcomes }
}
```

- [ ] **Step 4: Run the evaluator test**

Run: `cd 11_frontend && npx vitest run src/lib/alarms/evaluate.test.ts`

Expected: PASS, ten tests. If `describes the comparison in the rule’s own unit` fails on spacing,
compare against `AlarmContext.tsx`'s original template literal — the description strings are
deliberately byte-identical to what shipped, because they are already stored in
`activeAlarms` in operators' browsers.

- [ ] **Step 5: Write the failing context test**

Create `11_frontend/src/context/AlarmContext.evaluation.test.tsx`. The feed has to *grow* between
commits, which a plain module-level array cannot do — the provider would never re-render. A
`useSyncExternalStore` in the mock gives a feed the test can push to inside `act`.

```tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import { AlarmProvider, useAlarms } from './AlarmContext';
import { unsGraphQLClient } from '../services/graphql/client';
import type { AlertRule } from '../types/alarm';
import type { MqttMessage } from '../types/uns';

const LINE = 'CovestroAG/Dormagen/Production/Line1';

let feed: MqttMessage[] = [];
const listeners = new Set<() => void>();
const subscribeFeed = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const getFeed = () => feed;

/** Prepend to the feed the way UNSContext does, and let the provider see it. */
function push(...messages: MqttMessage[]) {
  act(() => {
    for (const message of messages) {
      feed = [message, ...feed];
    }
    listeners.forEach((fn) => fn());
  });
}

vi.mock('./UNSContext', () => ({
  useUNS: () => ({ mqttFeed: React.useSyncExternalStore(subscribeFeed, getFeed) }),
}));

vi.mock('./AuthContext', () => ({
  useAuth: () => ({ currentUser: { id: 'u-test', name: 'Test Operator', role: 'operator' } }),
}));

vi.mock('../services/graphql/client', () => ({
  unsGraphQLClient: {
    getAlertRules: vi.fn(),
    saveAlertRules: vi.fn(),
    saveAlertRule: vi.fn(),
    setAlertRuleEnabled: vi.fn(),
    deleteAlertRule: vi.fn(),
    recordAlertRuleEvaluation: vi.fn(),
  },
}));

const mocked = vi.mocked(unsGraphQLClient);

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r-temp',
    name: 'Line 1 temperature high',
    description: '',
    enabled: true,
    severity: 'HIGH',
    category: 'TEMPERATURE',
    topic: `${LINE}/#`,
    metricField: 'temp',
    condition: 'GREATER_THAN',
    thresholdValue: 80,
    unit: '°C',
    targetRoles: ['operator'],
    autoResolveOnNormal: false,
    // Off, so jsdom needs no AudioContext.
    actions: { inAppNotification: true, audioChime: false, mqttPublishOnTrigger: false, emailWebhook: false },
    triggerCount: 0,
    createdAt: '2026-09-01T00:00:00.000Z',
    updatedAt: '2026-09-01T00:00:00.000Z',
    ...overrides,
  };
}

function message(id: string, topic: string, payload: MqttMessage['payload']): MqttMessage {
  return { id, topic, payload, timestamp: '2026-09-02T10:00:00.000Z' };
}

type Ctx = ReturnType<typeof useAlarms>;
let ctx: Ctx | null = null;

const Probe: React.FC = () => {
  ctx = useAlarms();
  return null;
};

async function mount() {
  render(
    <AlarmProvider>
      <Probe />
    </AlarmProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AlarmProvider evaluation coverage', () => {
  beforeEach(() => {
    localStorage.clear();
    feed = [];
    ctx = null;
    mocked.getAlertRules.mockResolvedValue([rule()]);
    mocked.saveAlertRules.mockResolvedValue([]);
    mocked.recordAlertRuleEvaluation.mockResolvedValue(undefined as never);
    // toggleRuleEnabled chains .then() on this, so it has to be a promise.
    mocked.setAlertRuleEnabled.mockResolvedValue(null as never);
  });

  afterEach(() => {
    listeners.clear();
    vi.resetAllMocks();
  });

  // The defect this task closes.
  it('catches a breach that is not the newest message in the batch', async () => {
    await mount();

    push(
      message('m1', `${LINE}/Cell1`, { temp: 60 }),
      message('m2', `${LINE}/Cell1`, { temp: 91 }),
      message('m3', `${LINE}/Cell2`, { unrelated: 1 }),
    );

    expect(ctx?.activeAlarms).toHaveLength(1);
    expect(ctx?.activeAlarms[0].currentValue).toBe(91);
  });

  it('counts one trigger and writes one audit entry per breach', async () => {
    await mount();

    push(message('m1', `${LINE}/Cell1`, { temp: 91 }));

    expect(ctx?.activeAlarms).toHaveLength(1);
    expect(ctx?.auditLog.filter((e) => e.action === 'TRIGGERED')).toHaveLength(1);
    expect(ctx?.rules[0].triggerCount).toBe(1);
    expect(mocked.recordAlertRuleEvaluation).toHaveBeenCalledTimes(1);
    expect(mocked.recordAlertRuleEvaluation).toHaveBeenCalledWith('r-temp', true);
  });

  it('does not re-evaluate a message it has already seen', async () => {
    await mount();

    push(message('m1', `${LINE}/Cell1`, { temp: 91 }));
    const triggers = ctx?.auditLog.filter((e) => e.action === 'TRIGGERED').length;

    push(message('m2', `${LINE}/Cell2`, { unrelated: 1 }));

    expect(ctx?.auditLog.filter((e) => e.action === 'TRIGGERED')).toHaveLength(triggers!);
    expect(ctx?.activeAlarms).toHaveLength(1);
  });

  it('still re-evaluates the newest message when the rules change', async () => {
    mocked.getAlertRules.mockResolvedValue([rule({ enabled: false })]);
    await mount();

    push(message('m1', `${LINE}/Cell1`, { temp: 91 }));
    expect(ctx?.activeAlarms).toHaveLength(0);

    // Enabling a rule while a value is already breaching must raise the alarm now, not on
    // whatever the plant happens to publish next.
    await act(async () => {
      ctx?.toggleRuleEnabled('r-temp', true);
    });

    expect(ctx?.activeAlarms).toHaveLength(1);
  });

  it('auto-resolves when a breach and a recovery arrive in the same batch', async () => {
    mocked.getAlertRules.mockResolvedValue([rule({ autoResolveOnNormal: true })]);
    await mount();

    push(
      message('m1', `${LINE}/Cell1`, { temp: 91 }),
      message('m2', `${LINE}/Cell1`, { temp: 64 }),
    );

    expect(ctx?.activeAlarms).toHaveLength(1);
    expect(ctx?.activeAlarms[0].status).toBe('RESOLVED');
  });
});
```

`toggleRuleEnabled(ruleId, enabled)` is already on `AlarmContextType` (`:324`) and takes both
arguments, so this test adds nothing to the context. It reaches
`unsGraphQLClient.setAlertRuleEnabled` — its own narrow mutation, not `saveAlertRule` — and chains
`.then()` on the result, which is why that mock has to resolve rather than return `undefined`.

- [ ] **Step 6: Run it and watch the right things fail**

Run: `cd 11_frontend && npx vitest run src/context/AlarmContext.evaluation.test.tsx`

Expected: the first test FAILS with `0` alarms — `m2`'s breach was dropped. The second may pass or
fail depending on whether Testing Library's `act` triggers the double updater invocation; either
way it is pinned after Step 7.

- [ ] **Step 7: Replace the effect in AlarmContext**

In `11_frontend/src/context/AlarmContext.tsx`:

1. Add the import beside the others:
   ```ts
   import { evaluateFeed, type AlarmClock } from '../lib/alarms/evaluate'
   ```
   and remove the now-unused `topicMatchesFilter` import if the evaluation effect was its only
   caller — check with `grep -n "topicMatchesFilter" src/context/AlarmContext.tsx` after the edit.

2. Add a module-level clock, next to `STORAGE_KEYS`. It is module scope so it never becomes an
   effect dependency:
   ```ts
   const ALARM_CLOCK: AlarmClock = {
     now: () => new Date().toISOString(),
     newAlarmId: () => `alm-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
   }
   ```

3. Delete the whole `evaluateCondition` helper (`:578`–`:636` in the shipped file). It now lives in
   `lib/alarms/evaluate.ts` as `conditionResult`. It has **two** callers, not one: the evaluation
   effect, and `testTriggerRule` (`:898`). Fix the second one now, or the build breaks:

   ```tsx
       const evalResult = conditionResult(rule, testValue);
   ```

   and its use one line further down, where `desc` became `description`:

   ```tsx
         conditionDescription: `${evalResult.description} (Manual Diagnostic Trigger)`,
   ```

   While in that object, the `topic` line invents a plant path for a wildcard rule:

   ```tsx
         topic: rule.topic === '*' ? 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature' : rule.topic,
   ```

   `Reactor_01` is one of the fabrications Task 20 deleted from `INITIAL_RULES`; this is the last
   copy of it in the file, and it labels an engineer's diagnostic alarm with a vessel that does not
   exist. A rule on `*` genuinely has no topic, so say so:

   ```tsx
         topic: rule.topic,
   ```

4. Add these two refs above the evaluation effect:
   ```tsx
   /**
    * The alarms the evaluator folds over.
    *
    * A ref, not a dependency: depending on `activeAlarms` would re-run evaluation every time
    * an operator acknowledged something. Declared before the evaluation effect so that on a
    * commit which changed both, this one runs first.
    */
   const activeAlarmsRef = useRef(activeAlarms);
   useEffect(() => {
     activeAlarmsRef.current = activeAlarms;
   }, [activeAlarms]);

   /** The newest message already evaluated. Everything above it in the feed is new. */
   const lastEvaluatedIdRef = useRef<string | null>(null);
   ```

5. Replace the entire evaluation `useEffect` — from `if (mqttFeed.length === 0) return;` through
   the closing `}, [mqttFeed, rules, playAlarmChime, logAlarmAudit, reportEvaluation]);` — with:

   ```tsx
   // Evaluate every message that arrived since the last run, against every enabled rule.
   useEffect(() => {
     if (mqttFeed.length === 0) return;

     // The feed is newest-first. Everything above the last message we evaluated is new.
     // findIndex returns -1 when that message has aged out of the ring buffer, and 0 when
     // nothing arrived and this run was caused by a rules change — Math.max(1, …) turns both
     // into "evaluate the newest message", which is exactly what this effect used to do.
     const seenIndex = lastEvaluatedIdRef.current
       ? mqttFeed.findIndex((m) => m.id === lastEvaluatedIdRef.current)
       : -1;
     const fresh = mqttFeed.slice(0, Math.max(1, seenIndex)).reverse();
     lastEvaluatedIdRef.current = mqttFeed[0].id;

     const { alarms, outcomes } = evaluateFeed(fresh, rules, activeAlarmsRef.current, ALARM_CLOCK);

     if (alarms !== activeAlarmsRef.current) {
       // Written before setState so that StrictMode's second pass folds over the alarms this
       // pass produced, instead of raising every one of them a second time.
       activeAlarmsRef.current = alarms;
       setActiveAlarms(alarms);
     }

     for (const outcome of outcomes) {
       if (outcome.kind === 'QUIET') {
         reportEvaluation(outcome.rule.id, false);
         continue;
       }
       if (outcome.kind === 'TRIGGERED') {
         if (outcome.rule.actions.audioChime) {
           playAlarmChime(outcome.rule.severity);
         }
         // The counter is the platform's — every console watching this rule adds to the same
         // total — and is incremented here too so the number moves without a round trip.
         setRules((prev) =>
           prev.map((r) =>
             r.id === outcome.rule.id
               ? { ...r, triggerCount: r.triggerCount + 1, lastTriggeredAt: ALARM_CLOCK.now() }
               : r,
           ),
         );
         reportEvaluation(outcome.rule.id, true);
         logAlarmAudit(
           outcome.alarm.id,
           outcome.rule.name,
           outcome.alarm.topic,
           outcome.rule.severity,
           'TRIGGERED',
           `Live threshold breach: ${outcome.description}. Target roles: ${outcome.rule.targetRoles.join(', ')}`,
         );
         continue;
       }
       if (outcome.kind === 'CLEARED') {
         logAlarmAudit(
           outcome.alarm.id,
           outcome.rule.name,
           outcome.alarm.topic,
           outcome.rule.severity,
           'CLEARED',
           `Value returned to safe range (${String(outcome.value)}). Auto-resolved.`,
         );
       }
       // UPDATED changes a value on an alarm already on screen. No chime, no audit entry and
       // no evaluation report — that is what shipped, and repeating any of them would turn a
       // steady breach into a stream of duplicates.
     }
   }, [mqttFeed, rules, playAlarmChime, logAlarmAudit, reportEvaluation]);
   ```

Note what moved and what did not: every side effect is now outside a state updater, and
`setActiveAlarms` receives a value rather than a callback, because the evaluator has already done
the folding.

- [ ] **Step 8: Run both test files**

```bash
cd 11_frontend
npx vitest run src/lib/alarms/evaluate.test.ts src/context/AlarmContext.evaluation.test.tsx
```

Expected: PASS. If `still re-evaluates the newest message when the rules change` fails, the effect
is missing the `Math.max(1, …)`: with `seenIndex === 0` a bare `slice(0, 0)` evaluates nothing.

- [ ] **Step 9: Confirm Task 20's test still passes, and the suite with it**

```bash
cd 11_frontend
npx tsc --noEmit
npx vitest run
```

Expected: green, including `src/context/AlarmContext.test.tsx`. That file's `raises an alarm when a
filter with both + and # covers the topic` case exercises the new path with a one-message feed, so
it is the check that this task preserved the single-message behaviour.

- [ ] **Step 10: Verify the dev-mode duplication is gone by hand**

```bash
cd 11_frontend && npm run dev
```

With the simulator running, configure one rule that breaches, and watch the Alarms audit trail: one
`TRIGGERED` entry, and `triggerCount` moving by one. Before this task, StrictMode produced two of
each. Stop the dev server when done.

- [ ] **Step 11: Commit**

```bash
cd 11_frontend
git add src/lib/alarms/evaluate.ts src/lib/alarms/evaluate.test.ts \
        src/context/AlarmContext.tsx src/context/AlarmContext.evaluation.test.tsx
git commit -m "fix(frontend): evaluate every message in the feed against every rule

The evaluation effect read mqttFeed[0] and dropped the rest of the batch. With
the default '#' subscription the messages in one React commit are usually
different topics, so a rule watching topic B simply never saw B whenever A and
C arrived alongside it — an alarm system going quiet with nothing on screen to
say so.

Evaluation is now a pure fold in lib/alarms/evaluate.ts over the messages that
arrived since the last run, oldest first, so a breach that recovered inside one
batch ends on the recovery. The side effects moved out of the setActiveAlarms
updater: under StrictMode that updater ran twice, double-counting every trigger
and writing two audit entries per breach in dev.

Single-message behaviour is unchanged, including a rules change re-evaluating
the newest reading."
```

**Definition of done:**
- A breach anywhere in a batch raises its alarm, asserted by test at both the evaluator and the
  provider level.
- A breach and a recovery in the same batch end `RESOLVED` when the rule auto-resolves.
- One breach produces one audit entry, one `triggerCount` increment and one
  `recordAlertRuleEvaluation(id, true)` — asserted by test, and confirmed by hand in StrictMode.
- A message already evaluated is not evaluated again; a rules change still re-evaluates the newest.
- No side effect is called from inside a `set*` updater in `AlarmContext.tsx`:
  `grep -n "setActiveAlarms((prev" src/context/AlarmContext.tsx` returns only the acknowledge,
  resolve and note actions, none of which log from inside the callback.
- `evaluateCondition` no longer exists in `AlarmContext.tsx`; `conditionResult` is its only
  implementation, and `testTriggerRule` calls it.
- `grep -rn "Reactor_01" 11_frontend/src` is empty.
- `npx tsc --noEmit` clean; `npx vitest run` green.

---

## Task 24: ALARMS ▸ rule editor — separate what this console does from what it only records

Task 20 deleted the fictional rules and Task 23 made evaluation cover the whole feed. What is left
is the form that authors a rule, and it promises four things the platform does not do — plus it
hides three settings the platform's own schema stores.

**The seven findings, verified against the server schema and the ADR:**

1. **`mqttPublishOnTrigger` publishes nothing, and defaults to on.** The checkbox at
   `AlertRuleEditorModal.tsx:508`–`:519` reads `Publish to MQTT Alarm Topic`, the topic input at
   `:531`–`:545` appears when it is ticked, and `:96`–`:98` default it to **`true`** for every new
   rule. Nothing in `11_frontend/src` publishes to MQTT and nothing can: the browser never connects
   to the broker, and ADR-0005 rejected the MQTT write path for exactly this class of data —
   *"Publishing rules to MQTT and letting the historian persist them was rejected."* There is no
   mutation that asks the server to publish on the console's behalf either.
2. **`emailWebhook` and `webhookUrl` have no controls at all.** They are state at `:100`–`:103`,
   they are written on save at `:167`–`:168`, and `setEmailWebhook`/`setWebhookUrl` are never
   called. So every rule this console saves carries `emailWebhook: false` and
   `webhookUrl: 'https://alerts.plant.internal/webhook'` — an invented host, silently persisted to
   shared Postgres, that no engineer chose and no engineer can change here.
3. **`delaySeconds` has no control either**, and nothing debounces. State at `:79`, saved at
   `:157`, `setDelaySeconds` never called. A rule authored elsewhere with a 30-second delay is
   round-tripped intact and then evaluated with no delay at all.
4. **Escalation is configurable and inert.** The role select (`:441`–`:457`) and the timeout
   (`:461`–`:475`) both save. `grep -n "escalat" src/context/AlarmContext.tsx` finds only
   `escalated: false` assignments — no timer, no comparison against
   `escalationTimeoutMinutes`, and although `AlarmAuditEntry['action']` includes `'ESCALATED'`,
   nothing ever writes one. "Escalation Target Role (If Unacknowledged)" describes a service that
   does not exist.
5. **`inAppNotification` is read by nobody.**
   `grep -rn "inAppNotification" src/` finds the type, the two mapper directions, the GraphQL
   selection set and this checkbox. No component consults it before showing an alarm, so
   `In-App Incident Banner` is on the same footing as the MQTT box: stored, not honoured.
6. **`STALE_TIMEOUT` cannot fire.** It is offered as a condition (`:52`, *"Stale Timeout (No update
   for X min)"*) and as a category (`:36`). Task 23's `conditionResult` returns
   `breached: false` for it, because a feed carries arrivals and a stale timeout is an *absence* —
   detecting it needs a timer over `lastUpdated` per topic, which is a feature, not a fix. Offering
   it unlabelled means an operator can author a rule that is guaranteed never to trip.
7. **The form is pre-filled with the plant Task 20 deleted.** `:69` defaults `topic` to
   `CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature`, `:70` defaults `metricField` to
   `temp_celsius`, `:99` defaults the alarm topic to `alarms/plant/critical`. `Reactor_01` and
   `Polyurethane` appear nowhere in `conf/` or `99_simulator/`. A new rule therefore opens
   pre-aimed at a vessel that does not exist, and one click on Save writes it to shared Postgres.

**Why the answer is labelling, not deletion.** Six of these seven fields are real columns on the
server's Alert Rule: `07_uns_graphql/src/uns_graphql/type/alert_rule.py:106`–`:117` declares
`delay_seconds`, `escalation_role`, `escalation_timeout_minutes`, `mqtt_publish_on_trigger`,
`mqtt_alarm_topic`, `email_webhook` and `webhook_url`, and `queries.ts:249`–`:258` already selects
all of them. They are not frontend inventions — they are the dispatch policy a future service will
read, and ADR-0005 says so plainly: *"Moving evaluation into a service is now possible — the rules
are readable by anything with a database connection — but it is not done here."*

Deleting the controls would mean an OT engineer cannot record the escalation policy their site
already runs on paper, and would leave three fields being written from invented defaults. Keeping
them unlabelled is the lie. So: keep every field, give the three hidden ones real controls, and
split the form so it says which settings this console acts on and which it only stores. That is one
honest sentence away from the current file and it costs no capability.

**Files:**
- Modify: `11_frontend/src/components/alarms/AlertRuleEditorModal.tsx`
- Test: `11_frontend/src/components/alarms/AlertRuleEditorModal.test.tsx` (create)

**Interfaces:**
- Consumes: `BrowserEvaluationNotice` from `src/components/alarms/BrowserEvaluationNotice.tsx`
  (Task 14); `useAlarms().createRule` and `.updateRule`, `useUNS().allLoadedNodes` — all already
  used by this file and unchanged.
- Produces: no new export, and no change to `AlertRule`. The saved object keeps every field it
  writes today; only the defaults and the labels change. Test ids: `rule-editor`,
  `rule-editor-acts`, `rule-editor-recorded`, `rule-editor-save`, `rule-editor-error`.

- [ ] **Step 1: Confirm the four claims that matter, in the tree**

```bash
cd 11_frontend
grep -rn "inAppNotification" src/ | grep -v "types/alarm\|map-alert-rules\|queries.ts\|graphql/types\|AlertRuleEditorModal\|AlarmContext"
grep -n "escalat" src/context/AlarmContext.tsx
grep -rn "mqttAlarmTopic\|webhookUrl" src/ | grep -v "types/alarm\|map-alert-rules\|queries.ts\|graphql/types\|AlertRuleEditorModal\|AlarmContext"
grep -rn "Reactor_01\|temp_celsius\|alerts.plant.internal" src/
```

Expected: the first and third commands print nothing — no consumer reads `inAppNotification`,
`mqttAlarmTopic` or `webhookUrl`. The second prints only `escalated: false` lines. The fourth prints
only `AlertRuleEditorModal.tsx`, because Task 20 and Task 23 removed the rest. If any of these turns
up a real consumer, that field moves into the "acts now" group in Step 4 instead — the split is a
statement of fact, so it has to follow whatever the tree says today.

- [ ] **Step 2: Write the failing editor test**

Create `11_frontend/src/components/alarms/AlertRuleEditorModal.test.tsx`:

```tsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AlertRuleEditorModal } from './AlertRuleEditorModal';

const createRule = vi.fn();
const updateRule = vi.fn();

vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ createRule, updateRule }),
}));

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({ allLoadedNodes: [] }),
}));

describe('AlertRuleEditorModal', () => {
  beforeEach(() => {
    createRule.mockReset();
    updateRule.mockReset();
  });

  it('opens with no plant pre-filled', () => {
    render(<AlertRuleEditorModal rule={null} onClose={vi.fn()} />);

    expect(screen.getByLabelText(/topic/i)).toHaveValue('');
    expect(screen.getByLabelText(/metric field/i)).toHaveValue('');
    expect(screen.queryByDisplayValue(/Reactor_01/)).toBeNull();
    expect(screen.queryByDisplayValue(/alerts\.plant\.internal/)).toBeNull();
    expect(screen.queryByDisplayValue(/alarms\/plant\/critical/)).toBeNull();
  });

  it('will not save a rule with no topic', async () => {
    const user = userEvent.setup();
    render(<AlertRuleEditorModal rule={null} onClose={vi.fn()} />);

    await user.type(screen.getByLabelText(/rule name/i), 'Line 1 temp high');
    await user.click(screen.getByTestId('rule-editor-save'));

    expect(createRule).not.toHaveBeenCalled();
    expect(screen.getByTestId('rule-editor-error')).toHaveTextContent(/topic/i);
  });

  it('says which settings this console acts on and which it only stores', () => {
    render(<AlertRuleEditorModal rule={null} onClose={vi.fn()} />);

    const acts = screen.getByTestId('rule-editor-acts');
    expect(acts).toHaveTextContent(/Industrial audio chime/i);
    expect(acts).toHaveTextContent(/Auto-resolve/i);

    const recorded = screen.getByTestId('rule-editor-recorded');
    expect(recorded).toHaveTextContent(/nothing acts on these yet/i);
    expect(recorded).toHaveTextContent(/Publish to an MQTT alarm topic/i);
    expect(recorded).toHaveTextContent(/Escalate if unacknowledged/i);
    expect(recorded).toHaveTextContent(/In-app incident banner/i);
  });

  it('gives the three hidden fields real controls', async () => {
    const user = userEvent.setup();
    render(<AlertRuleEditorModal rule={null} onClose={vi.fn()} />);

    await user.type(screen.getByLabelText(/rule name/i), 'Line 1 temp high');
    await user.type(screen.getByLabelText(/^topic/i), 'CovestroAG/Dormagen/Production/Line1/temp');
    await user.type(screen.getByLabelText(/metric field/i), 'temp');
    await user.clear(screen.getByLabelText(/trigger delay/i));
    await user.type(screen.getByLabelText(/trigger delay/i), '30');
    await user.click(screen.getByLabelText(/send a webhook/i));
    await user.type(screen.getByLabelText(/webhook url/i), 'https://ops.example.test/hook');
    await user.click(screen.getByTestId('rule-editor-save'));

    expect(createRule).toHaveBeenCalledTimes(1);
    expect(createRule.mock.calls[0][0]).toMatchObject({
      topic: 'CovestroAG/Dormagen/Production/Line1/temp',
      metricField: 'temp',
      delaySeconds: 30,
      actions: {
        emailWebhook: true,
        webhookUrl: 'https://ops.example.test/hook',
        // Nothing publishes to MQTT, so a new rule must not claim it does.
        mqttPublishOnTrigger: false,
      },
    });
  });

  it('marks the condition this console cannot evaluate', () => {
    render(<AlertRuleEditorModal rule={null} onClose={vi.fn()} />);

    expect(
      screen.getByRole('option', { name: /stale timeout .*not evaluated here/i }),
    ).toBeInTheDocument();
  });

  it('round-trips a rule authored elsewhere without changing what it did not touch', async () => {
    const user = userEvent.setup();
    const existing = {
      id: 'r-1',
      name: 'Authored by another tool',
      description: '',
      enabled: true,
      severity: 'HIGH' as const,
      category: 'PRESSURE' as const,
      topic: 'CovestroAG/Dormagen/Production/Line1/pressure',
      metricField: 'bar',
      condition: 'GREATER_THAN' as const,
      thresholdValue: 135,
      unit: 'bar',
      delaySeconds: 45,
      targetRoles: ['engineer' as const],
      escalationRole: 'admin' as const,
      escalationTimeoutMinutes: 20,
      autoResolveOnNormal: true,
      actions: {
        inAppNotification: true,
        audioChime: false,
        mqttPublishOnTrigger: true,
        mqttAlarmTopic: 'alarms/line1/pressure',
        emailWebhook: true,
        webhookUrl: 'https://ops.example.test/existing',
      },
      triggerCount: 3,
      createdAt: '2026-08-01T00:00:00.000Z',
      updatedAt: '2026-08-01T00:00:00.000Z',
    };

    render(<AlertRuleEditorModal rule={existing} onClose={vi.fn()} />);
    await user.click(screen.getByTestId('rule-editor-save'));

    expect(updateRule).toHaveBeenCalledTimes(1);
    expect(updateRule.mock.calls[0][1]).toMatchObject({
      delaySeconds: 45,
      escalationTimeoutMinutes: 20,
      actions: {
        mqttPublishOnTrigger: true,
        mqttAlarmTopic: 'alarms/line1/pressure',
        emailWebhook: true,
        webhookUrl: 'https://ops.example.test/existing',
      },
    });
  });
});
```

The last test is the one that keeps this task honest in the other direction: labelling a field as
"not acted on" is not a licence to drop it on save.

- [ ] **Step 3: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/components/alarms/AlertRuleEditorModal.test.tsx`

Expected: FAIL on nearly every case — the topic is pre-filled with `Reactor_01`, there are no
`rule-editor-*` test ids, the delay and webhook controls do not exist, and no label distinguishes
the two groups. `will not save a rule with no topic` fails only on the missing test ids, not on the
check itself: `handleSave` already rejects a blank topic at `:119`–`:121` with *"Target topic path is
required."* That is the behaviour the test pins; do not add a second check for it.

- [ ] **Step 4: Blank the invented defaults**

In `11_frontend/src/components/alarms/AlertRuleEditorModal.tsx`, replace the defaults at `:69`–`:70`:

```tsx
  // No default plant. A rule aimed at a vessel nobody chose is one Save away from shared Postgres.
  const [topic, setTopic] = useState(rule?.topic || '');
  const [metricField, setMetricField] = useState(rule?.metricField || '');
```

and at `:96`–`:103`:

```tsx
  // Off by default: nothing in this console publishes to MQTT (ADR-0005), so a new rule must
  // not be born claiming that it does.
  const [mqttPublishOnTrigger, setMqttPublishOnTrigger] = useState(
    rule?.actions.mqttPublishOnTrigger ?? false
  );
  const [mqttAlarmTopic, setMqttAlarmTopic] = useState(rule?.actions.mqttAlarmTopic || '');
  const [emailWebhook, setEmailWebhook] = useState(rule?.actions.emailWebhook ?? false);
  const [webhookUrl, setWebhookUrl] = useState(rule?.actions.webhookUrl || '');
```

Leave `thresholdValue`, `thresholdUpperValue`, `unit` and `severity` alone: `85`, `120`, `°C` and
`HIGH` are form conveniences, not claims about this plant, and an engineer overwrites them while
typing the threshold they came to type.

- [ ] **Step 5: Label the condition that cannot fire, and stop the header promising dispatch**

Still in the same file, replace the `STALE_TIMEOUT` entry in `CONDITIONS` (`:52`):

```tsx
  {
    label: 'Stale Timeout (no update for X seconds) — not evaluated here',
    value: 'STALE_TIMEOUT',
  },
```

Add the reason directly under the condition select, so the label is not the only explanation. Place
it after the `</select>` that renders `CONDITIONS.map` (`:343`–`:350`):

```tsx
              {condition === 'STALE_TIMEOUT' && (
                <p className="mt-1 text-[10px] text-amber-700 dark:text-[#FFC107]">
                  This console evaluates rules from messages as they arrive, so it cannot see a
                  message that never came. The rule is stored, and will be evaluated once a service
                  does the watching.
                </p>
              )}
```

`handleSave` already rejects a blank name, topic, metric field and empty `targetRoles`
(`:118`–`:134`). Leave all four checks exactly as they are — Step 4 only removed the pre-fill that
was hiding the topic check from anyone who never cleared the field. Do not restate the messages.

The modal subtitle at `:196`–`:198` is the last promise in the header:

```tsx
              <p className="text-[10px] text-[#64748B] dark:text-[#94A3B8] text-pretty">
                Threshold conditions and role targeting, evaluated in this browser.
              </p>
```

`dispatch channels` comes out because sections 4 and 5 now say precisely which channels work.

Give the error paragraph and the Save button their test ids while you are in the file:
`data-testid="rule-editor-error"` on the element that renders `validationError`, and
`data-testid="rule-editor-save"` on the Save button in the footer. Put
`data-testid="rule-editor"` on the modal's outermost panel.

Every input this test addresses by label needs a real association, not a nearby `<label>` with no
`htmlFor`. Give each control an `id` and its label a matching `htmlFor` — `rule-name`, `rule-topic`,
`rule-metric-field`, `rule-condition`, `rule-delay`, `rule-webhook`, `rule-webhook-url`. That is
also what makes the form keyboard-navigable, which the spec's focus-ring requirement assumes.

- [ ] **Step 6: Split section 4 into what happens and what is stored**

Replace the whole of section 4 — from the `4. Dispatch Actions & Notifications` heading (`:483`)
through the closing `</div>` of the `mqttPublishOnTrigger &&` block (`:546`) — with two groups. The
escalation pair moves here too, out of section 3.

```tsx
          {/* Section 4: what this console does when the condition breaches */}
          <div
            data-testid="rule-editor-acts"
            className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]"
          >
            <div className="text-[11px] font-mono font-bold text-amber-700 dark:text-[#FFC107] uppercase tracking-wider">
              4. What this console does on a breach
            </div>
            <BrowserEvaluationNotice />

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <label
                htmlFor="rule-audio-chime"
                className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer"
              >
                <input
                  id="rule-audio-chime"
                  type="checkbox"
                  checked={audioChime}
                  onChange={(e) => setAudioChime(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Volume2 className="w-3.5 h-3.5 text-rose-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">
                  Industrial audio chime, in this browser
                </span>
              </label>

              <label
                htmlFor="rule-auto-resolve"
                className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer"
              >
                <input
                  id="rule-auto-resolve"
                  type="checkbox"
                  checked={autoResolveOnNormal}
                  onChange={(e) => setAutoResolveOnNormal(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Check className="w-3.5 h-3.5 text-sky-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">
                  Auto-resolve when the value returns to range
                </span>
              </label>
            </div>
          </div>

          {/* Section 5: stored on the rule, honoured by nothing that exists yet */}
          <div
            data-testid="rule-editor-recorded"
            className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-dashed border-[#CBD5E1] dark:border-[#334155]"
          >
            <div className="text-[11px] font-mono font-bold text-[#64748B] dark:text-[#94A3B8] uppercase tracking-wider">
              5. Dispatch policy — recorded, not performed
            </div>
            <p className="text-[11px] text-[#64748B]">
              These are stored on the rule and shared with every console, and{' '}
              <strong>nothing acts on these yet</strong>. Dispatching a notification and escalating
              an unacknowledged alarm need a service that runs when nobody has the console open;
              this browser cannot publish to the broker or send a webhook. Record the policy your
              site runs on here, and it is waiting when that service arrives.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <label
                htmlFor="rule-in-app"
                className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer"
              >
                <input
                  id="rule-in-app"
                  type="checkbox"
                  checked={inAppNotification}
                  onChange={(e) => setInAppNotification(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Bell className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">
                  In-app incident banner
                </span>
              </label>

              <label
                htmlFor="rule-mqtt-publish"
                className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer"
              >
                <input
                  id="rule-mqtt-publish"
                  type="checkbox"
                  checked={mqttPublishOnTrigger}
                  onChange={(e) => setMqttPublishOnTrigger(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Send className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">
                  Publish to an MQTT alarm topic
                </span>
              </label>

              <label
                htmlFor="rule-webhook"
                className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer"
              >
                <input
                  id="rule-webhook"
                  type="checkbox"
                  checked={emailWebhook}
                  onChange={(e) => setEmailWebhook(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Mail className="w-3.5 h-3.5 text-violet-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">
                  Send a webhook
                </span>
              </label>

              <div>
                <label
                  htmlFor="rule-delay"
                  className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium"
                >
                  Trigger delay
                </label>
                <div className="flex items-center gap-1.5">
                  <input
                    id="rule-delay"
                    type="number"
                    value={delaySeconds}
                    onChange={(e) => setDelaySeconds(Number(e.target.value))}
                    min={0}
                    max={3600}
                    className="flex-1 bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                  <span className="text-[#64748B] font-mono text-[11px]">Seconds</span>
                </div>
              </div>
            </div>

            {mqttPublishOnTrigger && (
              <div>
                <label
                  htmlFor="rule-mqtt-topic"
                  className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium"
                >
                  MQTT alarm topic
                </label>
                <input
                  id="rule-mqtt-topic"
                  type="text"
                  value={mqttAlarmTopic}
                  onChange={(e) => setMqttAlarmTopic(e.target.value)}
                  placeholder="alarms/&lt;area&gt;/&lt;incident&gt;"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>
            )}

            {emailWebhook && (
              <div>
                <label
                  htmlFor="rule-webhook-url"
                  className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium"
                >
                  Webhook URL
                </label>
                <input
                  id="rule-webhook-url"
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>
            )}

            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="rule-escalation-role"
                  className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium"
                >
                  Escalate if unacknowledged, to
                </label>
                <select
                  id="rule-escalation-role"
                  value={escalationRole}
                  onChange={(e) => setEscalationRole(e.target.value as UserRole)}
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] cursor-pointer"
                >
                  {PREDEFINED_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_CONFIGS[r]?.label || r}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="rule-escalation-timeout"
                  className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium"
                >
                  Escalate after
                </label>
                <div className="flex items-center gap-1.5">
                  <input
                    id="rule-escalation-timeout"
                    type="number"
                    value={escalationTimeoutMinutes}
                    onChange={(e) => setEscalationTimeoutMinutes(Number(e.target.value))}
                    min={1}
                    max={120}
                    className="flex-1 bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                  <span className="text-[#64748B] font-mono text-[11px]">Minutes</span>
                </div>
              </div>
            </div>
          </div>
```

Then delete the old escalation block from section 3 — the `{/* Escalation Policy */}` div at
`:440`–`:476` — since it now lives in section 5. Section 3 keeps the role selector, which does act:
`myRoleAlarms` in `AlarmContext.tsx` filters on `targetRoles`.

Add the import at the top of the file:

```tsx
import { BrowserEvaluationNotice } from './BrowserEvaluationNotice';
```

`Sliders`, `Shield`, `Layers`, `Radio` and `ChevronDown` are used elsewhere in the file; `Mail` was
imported at `:10` and finally has a use. Run `npx tsc --noEmit` after this step and delete any icon
import that is now unused rather than guessing which.

- [ ] **Step 7: Run the editor test**

Run: `cd 11_frontend && npx vitest run src/components/alarms/AlertRuleEditorModal.test.tsx`

Expected: PASS, six tests. If `gives the three hidden fields real controls` fails because
`getByLabelText(/^topic/i)` matched two elements, the MQTT alarm topic label is colliding — it reads
`MQTT alarm topic`, which `/^topic/i` should not match; check that the ISA-95 topic field's label
really begins with the word Topic.

- [ ] **Step 8: Check the rest of the suite and the types**

```bash
cd 11_frontend
npx tsc --noEmit
npx vitest run
```

Expected: green. `AlarmManagementView.test.tsx` (Task 20) renders the list, not the modal, so it
should be unaffected; if it opens the editor, update its assertions to the new section headings
rather than reverting them here.

- [ ] **Step 9: Commit**

```bash
cd 11_frontend
git add src/components/alarms/AlertRuleEditorModal.tsx \
        src/components/alarms/AlertRuleEditorModal.test.tsx
git commit -m "fix(frontend): say which alarm actions this console performs

The rule editor offered an MQTT publish, an escalation policy and an in-app
banner that nothing honours, hid delaySeconds, emailWebhook and webhookUrl
behind no controls at all while still writing them, and opened pre-aimed at
Reactor_01 with a webhook pointed at alerts.plant.internal.

Every field stays — they are real columns on the server's Alert Rule and the
dispatch policy a future service will read (ADR-0005) — but the form now
separates what happens on a breach from what is only recorded, gives the three
hidden fields controls, marks STALE_TIMEOUT as something this console cannot
evaluate, and starts a new rule with no plant and no MQTT claim.

Values authored elsewhere round-trip untouched."
```

**Definition of done:**
- A new rule opens with an empty topic and metric field, and
  `grep -rn "Reactor_01\|temp_celsius\|alerts.plant.internal\|alarms/plant/critical" 11_frontend/src`
  is empty.
- A new rule saves with `mqttPublishOnTrigger: false`.
- `delaySeconds`, `emailWebhook` and `webhookUrl` are settable in the form, asserted by test.
- Saving a rule authored elsewhere preserves every dispatch field it arrived with, asserted by test.
- The form states, in words an operator can read, that dispatch and escalation are recorded and not
  performed, and `BrowserEvaluationNotice` appears in the editor.
- `STALE_TIMEOUT` is labelled as not evaluated here, and selecting it explains why.
- Every input the tests address has an `id` and a `<label htmlFor>`.
- `npx tsc --noEmit` clean; `npx vitest run` green.
