# Operations Console Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `11_frontend` into an eleven-destination operations console where every screen is reachable from plant vocabulary, every claim on screen is derived from a real response, and the OEE, Asset Model and downtime capabilities that already exist in the platform have a UI.

**Architecture:** The router gains five destinations and three redirects. A grouped nav rail replaces the badge-laden sidebar. PLANT becomes a six-tab workspace over a selected Asset, driven by the client reads added in the foundation plan. Every fabricated string in the shell is deleted rather than reworded, and the sub-11px type is raised to the spec's scale. No new GraphQL documents are written here — this plan consumes the client methods the foundation plan produced.

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

