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
      GrafanaEmbed.tsx                     CREATE  one iframe wrapper, three call sites
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
      AssetDetail.tsx                      CREATE
      UnmodelledTopicsList.tsx             CREATE
    namespace/
      NamespaceView.tsx                    CREATE  wraps the existing home/ components
    historian/
      HistorianView.tsx                    CREATE  wraps explore/, adds CSV
    health/
      HealthView.tsx                       CREATE  four honest sections
    home/                                  KEEP    UnsTreeView, LiveMqttFeed, PayloadInspector
    explore/                               KEEP    HistorianTable, HistorianTrendChart
    system/HomeView.tsx / SystemHealthView.tsx  DELETE after their replacements land
    landing/LandingView.tsx                MODIFY  fabricated figures removed
    auth/LoginView.tsx                     MODIFY  fabricated claim removed
    users/UserManagementView.tsx           MODIFY  read-only, labelled not enforced
  context/
    UNSContext.tsx                         MODIFY  NavigationTab, selectedAsset, jump targets
    AlarmContext.tsx                       MODIFY  INITIAL_RULES and restoreDefaults deleted
    AuthContext.tsx                        MODIFY  canAccessTab tab ids and plain names
  lib/
    csv/to-csv.ts                          CREATE  shared CSV serialiser
    grafana/dashboards.ts                  CREATE  UIDs and variable names in one place
```

`ConnectionChip.tsx` stays in `common/` although spec section 17 lists it under `layout/`. Moving it would touch every import for no behavioural gain; the spec's grouping is descriptive, not a filesystem requirement.

`components/home/` and `components/explore/` keep their leaf components — `NamespaceView` and `HistorianView` are new shells around them, not rewrites. Only the two view files that fabricate data (`HomeView.tsx`, `SystemHealthView.tsx`) are deleted.

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
          <Route path="/historian" element={<HistorianView />} />
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
      detail="Task 7 of the surfaces plan replaces this with the Asset canvas and its six tabs."
    />
  </section>
);
```

Repeat with the same shape for `shift/ShiftView.tsx` (heading `Shift & OEE`, Task 13), `assets/AssetsView.tsx` (heading `Assets`, Task 14), `namespace/NamespaceView.tsx` (heading `Namespace`, Task 15) and `health/HealthView.tsx` (heading `Health`, Task 17). Write each one out — do not import a shared placeholder, because each file gets fully replaced and a shared one would linger.

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

- [ ] **Step 6: Run the test**

```bash
cd 11_frontend && npx vitest run src/components/landing/landing-claims.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Sweep the whole module for survivors**

```bash
cd 11_frontend && grep -rn "62443\|99\.999\|TLS 1\.3\|Zero-Trust\|non-repudiable\|Certified" src
```

Expected: no output. If a string survives in a component the test does not render, fix it the same way and add that component to the test.

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/components/landing/ 11_frontend/src/components/auth/LoginView.tsx
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

Replace `getStatusColor` and `getStatusDot` (`:12-32`) with one lookup keyed on the four states, and derive everything shown from `connectionState`:

```tsx
import { connectionState } from '../../lib/health/connection-state';

const TONE: Record<string, { chip: string; dot: string }> = {
  LIVE: {
    chip: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-500/30',
    dot: 'bg-emerald-500 dark:bg-emerald-400',
  },
  CONNECTING: {
    chip: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-300 dark:border-sky-500/30',
    dot: 'bg-sky-500 animate-pulse',
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

Only `CONNECTING` pulses. A pulsing dot on a Live chip is decoration; a pulsing dot on a chip that is waiting is information.

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
                {health.lastPingMs === null ? '—' : `${health.lastPingMs} ms`}
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

PLANT ▸ Trend, SHIFT and HEALTH all embed a dashboard. The sub-path, kiosk parameter, theme and the deep-link variables get decided once. Nothing here invents a variable: `var-asset` exists on `uns-oee`, `var-topic` and `var-metric` on `uns-process-visualization`, and `uns-platform-observability` has none.

**Files:**
- Create: `11_frontend/src/lib/grafana/dashboards.ts`
- Create: `11_frontend/src/components/common/GrafanaEmbed.tsx`
- Test: `11_frontend/src/lib/grafana/dashboards.test.ts`
- Test: `11_frontend/src/components/common/GrafanaEmbed.test.tsx`

**Interfaces:**
- Consumes: `grafanaProxyTarget` and the console theme. The foundation plan added `grafanaHost`, `grafanaPort` and `grafanaProxyTarget` to `src/lib/platform/settings.ts` and the `/grafana` proxy to `nginx.conf` and `vite.config.ts`; the browser only ever uses the relative `/grafana` path, so it reads none of those three.
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

- [ ] **Step 5: Write `GrafanaEmbed.tsx`**

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
3. `assigned_by` carries the description "Attested by the caller, not authenticated: this platform has no authentication anywhere." The dialog therefore asks the operator to type a name and states plainly that nothing verifies it. It does **not** send `AuthContext`'s fabricated user, which would dress a made-up identity as a real one. The authentication plan replaces this field with the token subject.

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
