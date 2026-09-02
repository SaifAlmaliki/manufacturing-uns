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
