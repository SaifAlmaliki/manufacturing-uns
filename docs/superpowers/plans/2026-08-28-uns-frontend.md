# UNS Frontend Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `10_frontend` into a React console that reads the Unified Namespace through `07_uns_graphql`: lazy ISA-95 tree, live MQTT `#` feed, search, and historian with an optional numeric trend.

**Architecture:** The browser talks only to GraphQL (HTTP queries + WebSocket subscriptions). Vite proxies `/graphql` in development. Production is a separate nginx container; GraphQL gains CORS. Domain rules (tree merge, MQTT patch/insert, feed cap, Sparkplug detection, numeric paths) live in pure TypeScript modules with unit tests before UI is wired.

**Tech Stack:** React + TypeScript + Vite, Tailwind CSS, shadcn/ui primitives, React Router, Apollo Client 3 + `graphql-ws`, Recharts, Vitest + Testing Library. Backend: FastAPI CORSMiddleware on existing Strawberry `GraphQLRouter`.

## Global Constraints

- No auth in v1. No OEE/KPI cards. No Sparkplug protobuf decode in the browser. No Kafka UI. No BFF. Do not serve the UI from FastAPI.
- Tree queries never use `#`. Roots: `getUnsNodes(topics: [{ topic: "+" }])`. Expand `N`: `getUnsNodes(topics: [{ topic: "{N.namespace}/+" }])`.
- Live subscription is always `getMqttMessages(topics: [{ topic: "#" }])` for the whole app session. Selecting a node does not resubscribe.
- Sparkplug B topics start with `spBv1.0/`. They appear in the feed as a badge, never as JSON, and are never inserted into the tree.
- Feed: newest first, cap 500, pause drops incoming (does not queue). No live backfill after WS drop.
- Search does not replace or filter the left tree. Match list lives in the Explore right pane.
- Combined search uses one call: `getUnsNodesByProperty(propertyKeys, topics)` when both fields are set.
- Historian topic for a selected namespace `ns` is `ns/#`. Presets: 15m, 1h, 24h, custom. Block `from > to`.
- Copy: product name `Unified Namespace`. Empty tree: `No nodes yet — waiting for GraphQL / UNS data.` Empty feed: `No messages yet.` Search hint: `Enter a topic or property.` Zero hits: `No nodes match.` Empty historian: `No events in this range.` Can't reach API: `Can't reach GraphQL.` Historical inspector label: `Historical event`. Sparkplug badge: `Sparkplug B (binary)`. Invalid JSON row: `invalid JSON`. Missing payload: `No payload.`
- English only. Desktop-first. Dim tree nodes whose `lastUpdated` is older than 5 minutes.
- Dev GraphQL URL is relative `/graphql`. Prod requires `VITE_GRAPHQL_URL` or the app shows a blocking error (not a blank screen).
- Strawberry wire names are camelCase: `getUnsNodes`, `getUnsNodesByProperty`, `getHistoricEventsInTimeRange`, `getMqttMessages`, `nodeName`, `nodeType`, `lastUpdated`, `fromDatetime`, `toDatetime`, `propertyKeys`.
- Frontend tests mock GraphQL. Do not start MQTT, Neo4j, or Timescale for frontend tests. No Playwright in v1.
- Work in `10_frontend` (do not create a second app). Frequent commits. TDD for domain modules.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `07_uns_graphql/src/uns_graphql/uns_graphql_app.py` | CORS + explicit GraphQL WS protocols |
| `07_uns_graphql/test/test_uns_graphql_cors.py` | CORS preflight tests |
| `10_frontend/vite.config.ts` | React plugin, `/graphql` HTTP+WS proxy, Vitest |
| `10_frontend/src/index.css` | Tailwind + dark industrial tokens |
| `10_frontend/src/lib/utils.ts` | `cn()` |
| `10_frontend/src/lib/uns/sparkplug.ts` | `spBv1.0/` detection |
| `10_frontend/src/lib/uns/payload.ts` | Parse GraphQL JSON payload (string or object) |
| `10_frontend/src/lib/uns/topics.ts` | parent, children `+` topic, historian `#` topic, feed highlight |
| `10_frontend/src/lib/uns/stale.ts` | 5-minute dim rule |
| `10_frontend/src/lib/graphql/graphql-url.ts` | HTTP/WS URL + prod missing-env error |
| `10_frontend/src/lib/graphql/operations.ts` | gql documents |
| `10_frontend/src/lib/graphql/types.ts` | Hand-written types matching the schema |
| `10_frontend/src/lib/graphql/client.ts` | Apollo split link |
| `10_frontend/src/features/tree/tree-model.ts` | Merge GraphQL nodes into lazy tree |
| `10_frontend/src/features/tree/tree-mqtt.ts` | Patch loaded UNS node / insert child under expanded parent |
| `10_frontend/src/features/feed/feed-buffer.ts` | Ring buffer + pause |
| `10_frontend/src/features/explore/numeric-paths.ts` | Flatten numeric JSON leaves |
| `10_frontend/src/app/types.ts` | Shared UI/state types |
| `10_frontend/src/app/uns-reducer.ts` | App state transitions |
| `10_frontend/src/app/connection.ts` | Live / Degraded / Down |
| `10_frontend/src/app/UnsProvider.tsx` | Context |
| `10_frontend/src/components/ui/*` | Minimal shadcn-style Button, Badge, ScrollArea |
| `10_frontend/src/features/shell/AppShell.tsx` | Header + 3 resizable columns |
| `10_frontend/src/features/tree/TreePanel.tsx` | Lazy tree UI |
| `10_frontend/src/features/payload/PayloadPanel.tsx` | Node vs historical JSON |
| `10_frontend/src/features/feed/FeedPanel.tsx` | Live `#` feed |
| `10_frontend/src/features/explore/ExplorePanel.tsx` | Search, match list, historian, trend |
| `10_frontend/src/App.tsx` | Router + provider + GraphQL hooks |
| `10_frontend/Dockerfile`, `10_frontend/nginx.conf` | Static UI image |
| `docker-compose.yml` | `uns_frontend` service on port 8088 |
| `10_frontend/README.md` | How to run with GraphQL on `:8000` |

Delete when replacing the Vite demo: `10_frontend/src/main.ts`, `10_frontend/src/counter.ts`, `10_frontend/src/style.css` (replaced by `index.css`), unused demo assets if nothing imports them.

---

### Task 1: GraphQL CORS and WebSocket protocols

**Files:**
- Create: `07_uns_graphql/test/test_uns_graphql_cors.py`
- Modify: `07_uns_graphql/src/uns_graphql/uns_graphql_app.py`

**Interfaces:**
- Consumes: existing `UNSGraphql.app` (`FastAPI` with router prefix `/graphql`)
- Produces: CORS origins `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:8088`, `http://127.0.0.1:8088`; `GraphQLRouter` with `GRAPHQL_TRANSPORT_WS_PROTOCOL` and `GRAPHQL_WS_PROTOCOL`

- [ ] **Step 1: Write the failing CORS test**

```python
"""CORS for the UNS frontend origins."""

from fastapi.testclient import TestClient

from uns_graphql.uns_graphql_app import UNSGraphql

VITE_ORIGIN = "http://localhost:5173"
COMPOSE_UI_ORIGIN = "http://localhost:8088"


def test_cors_preflight_allows_vite_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": VITE_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == VITE_ORIGIN


def test_cors_preflight_allows_compose_ui_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": COMPOSE_UI_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == COMPOSE_UI_ORIGIN


def test_cors_preflight_rejects_unknown_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "http://evil.example"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from repo root, with the project venv that can import `uns_graphql`):

```bash
uv run pytest 07_uns_graphql/test/test_uns_graphql_cors.py -v
```

Expected: FAIL — `access-control-allow-origin` missing.

- [ ] **Step 3: Enable CORS and explicit subscription protocols**

In `uns_graphql_app.py`, add imports:

```python
from fastapi.middleware.cors import CORSMiddleware
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
```

Replace the `graphql_app` / `app` construction (keep schema and lifespan as they are) with:

```python
    CORS_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8088",
        "http://127.0.0.1:8088",
    ]

    graphql_app = GraphQLRouter(
        schema,
        subscription_protocols=[
            GRAPHQL_TRANSPORT_WS_PROTOCOL,
            GRAPHQL_WS_PROTOCOL,
        ],
    )
    LOGGER.info("GraphQL app created")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(graphql_app, prefix="/graphql")
    app.lifespan = lifespan
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest 07_uns_graphql/test/test_uns_graphql_cors.py 07_uns_graphql/test/test_uns_graphql_app.py -v
```

Expected: PASS (existing app tests still pass).

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/uns_graphql_app.py 07_uns_graphql/test/test_uns_graphql_cors.py
git commit -m "Allow frontend origins to call GraphQL over HTTP and WebSocket."
```

---

### Task 2: React, Tailwind, Vitest scaffold

**Files:**
- Create: `10_frontend/vite.config.ts`, `10_frontend/src/main.tsx`, `10_frontend/src/App.tsx`, `10_frontend/src/index.css`, `10_frontend/src/lib/utils.ts`, `10_frontend/src/test/setup.ts`, `10_frontend/src/vite-env.d.ts`
- Modify: `10_frontend/package.json`, `10_frontend/tsconfig.json`, `10_frontend/index.html`
- Delete: `10_frontend/src/main.ts`, `10_frontend/src/counter.ts`, `10_frontend/src/style.css`

**Interfaces:**
- Consumes: existing Vite 8 + TypeScript app
- Produces: `npm run test` (Vitest), `npm run dev` with proxy `/graphql` → `http://localhost:8000`, React entry `src/main.tsx`

- [ ] **Step 1: Install dependencies**

From `10_frontend`:

```bash
npm install react react-dom react-router-dom clsx tailwind-merge class-variance-authority lucide-react react-resizable-panels
npm install -D @types/react @types/react-dom @vitejs/plugin-react tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

- [ ] **Step 2: Write a failing render test**

Create `10_frontend/src/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'

test('renders Unified Namespace title', () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  )
  expect(screen.getByText('Unified Namespace')).toBeInTheDocument()
})
```

Create `10_frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 3: Run test to verify it fails**

Add scripts and config first so Vitest can run (minimal `App.tsx` that does **not** include the title yet, or omit `App.tsx` so the import fails). Preferred: create `App.tsx` that returns `null` so the assertion fails.

`10_frontend/vite.config.ts`:

```ts
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/graphql': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
  },
})
```

`tsconfig.json` — add `"jsx": "react-jsx"` to `compilerOptions`. Keep existing bundler options.

`package.json` scripts:

```json
"dev": "vite",
"build": "tsc && vite build",
"preview": "vite preview",
"test": "vitest run"
```

`index.html` — change script to `/src/main.tsx`, title to `Unified Namespace`.

`src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GRAPHQL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
```

`src/index.css`:

```css
@import "tailwindcss";

@theme {
  --color-console-bg: #0b0f14;
  --color-console-panel: #121821;
  --color-console-border: #243040;
  --color-console-text: #e6edf3;
  --color-console-muted: #8b9bb0;
  --color-console-accent: #3dd6c3;
  --color-console-warn: #e3b341;
  --color-console-danger: #e85d5d;
}

html,
body,
#app {
  height: 100%;
  margin: 0;
  background: var(--color-console-bg);
  color: var(--color-console-text);
  font-family: ui-sans-serif, system-ui, sans-serif;
}
```

`src/lib/utils.ts`:

```ts
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

Placeholder `src/App.tsx`:

```tsx
export function App() {
  return null
}
```

`src/main.tsx`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './index.css'

createRoot(document.getElementById('app')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
```

Run:

```bash
npm test
```

Expected: FAIL — unable to find `Unified Namespace`.

- [ ] **Step 4: Minimal pass (title only)**

```tsx
export function App() {
  return <h1>Unified Namespace</h1>
}
```

Run `npm test`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 10_frontend
git commit -m "Convert the frontend scaffold to React, Tailwind, and Vitest."
```

Do not commit `node_modules`. Keep `package-lock.json`.

---

### Task 3: Domain utilities (tree, feed, Sparkplug, payload, numeric paths)

**Files:**
- Create: `10_frontend/src/lib/uns/sparkplug.ts`, `10_frontend/src/lib/uns/payload.ts`, `10_frontend/src/lib/uns/topics.ts`, `10_frontend/src/lib/uns/stale.ts`, `10_frontend/src/features/tree/tree-model.ts`, `10_frontend/src/features/tree/tree-mqtt.ts`, `10_frontend/src/features/feed/feed-buffer.ts`, `10_frontend/src/features/explore/numeric-paths.ts`
- Test: `10_frontend/src/lib/uns/uns-domain.test.ts`, `10_frontend/src/features/tree/tree-model.test.ts`, `10_frontend/src/features/tree/tree-mqtt.test.ts`, `10_frontend/src/features/feed/feed-buffer.test.ts`, `10_frontend/src/features/explore/numeric-paths.test.ts`

**Interfaces:**
- Consumes: none
- Produces: functions listed in each file below. `UnsNodeRecord` is the canonical node shape for the rest of the app.

- [ ] **Step 1: Write failing tests**

`sparkplug.ts` tests in `uns-domain.test.ts`:

```ts
import { describe, expect, test } from 'vitest'
import { isSparkplugTopic, SPARKPLUG_PREFIX } from './sparkplug'
import { parseJsonPayload } from './payload'
import { childrenTopic, historianTopic, isFeedHighlight, parentNamespace } from './topics'
import { isStale } from './stale'

test('sparkplug prefix', () => {
  expect(SPARKPLUG_PREFIX).toBe('spBv1.0/')
  expect(isSparkplugTopic('spBv1.0/G/NDATA/E/D')).toBe(true)
  expect(isSparkplugTopic('ent/fac/line')).toBe(false)
})

test('topics helpers', () => {
  expect(parentNamespace('ent/fac/line')).toBe('ent/fac')
  expect(parentNamespace('ent')).toBe('')
  expect(childrenTopic('')).toBe('+')
  expect(childrenTopic('ent/fac')).toBe('ent/fac/+')
  expect(historianTopic('ent/fac')).toBe('ent/fac/#')
  expect(isFeedHighlight('ent/fac/line', 'ent/fac')).toBe(true)
  expect(isFeedHighlight('ent/fac', 'ent/fac')).toBe(true)
  expect(isFeedHighlight('other', 'ent/fac')).toBe(false)
})

test('parse json payload string or object', () => {
  expect(parseJsonPayload('{"a":1}')).toEqual({ ok: true, value: { a: 1 } })
  expect(parseJsonPayload({ a: 1 })).toEqual({ ok: true, value: { a: 1 } })
  expect(parseJsonPayload('not-json').ok).toBe(false)
})

test('stale after 5 minutes', () => {
  const now = Date.parse('2026-08-28T12:00:00Z')
  expect(isStale('2026-08-28T11:54:00Z', now)).toBe(true)
  expect(isStale('2026-08-28T11:56:00Z', now)).toBe(false)
})
```

`tree-model.test.ts`:

```ts
import { describe, expect, test } from 'vitest'
import { emptyTree, mergeGraphNodes, type UnsNodeRecord } from './tree-model'

function node(namespace: string, nodeType = 'DEVICE'): UnsNodeRecord {
  return {
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { rpm: 1 },
    created: '2026-01-01T00:00:00Z',
    lastUpdated: '2026-01-01T00:00:00Z',
  }
}

test('merges root nodes under empty parent', () => {
  const tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  expect(tree.nodes['acme']?.nodeType).toBe('ENTERPRISE')
  expect(tree.childrenByParent['']).toEqual(['acme'])
})

test('merges children under parent path', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  tree = mergeGraphNodes(tree, [node('acme/plant1', 'FACILITY')])
  expect(tree.childrenByParent['acme']).toEqual(['acme/plant1'])
})
```

`tree-mqtt.test.ts`:

```ts
import { expect, test } from 'vitest'
import { applyMqttToTree } from './tree-mqtt'
import { emptyTree, mergeGraphNodes, type UnsNodeRecord } from './tree-model'

function node(namespace: string, nodeType = 'LINE'): UnsNodeRecord {
  return {
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { rpm: 1 },
    created: '2026-01-01T00:00:00Z',
    lastUpdated: '2026-01-01T00:00:00Z',
  }
}

test('patches loaded uns node payload and timestamp', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme/l1')])
  tree = applyMqttToTree(tree, {
    topic: 'acme/l1',
    payload: { rpm: 9 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(tree.nodes['acme/l1']?.payload).toEqual({ rpm: 9 })
  expect(tree.nodes['acme/l1']?.lastUpdated).toBe('2026-08-28T12:00:00Z')
})

test('does not insert sparkplug into the tree', () => {
  const tree = applyMqttToTree(emptyTree(), {
    topic: 'spBv1.0/G/NDATA/E',
    payload: { x: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(tree.nodes['spBv1.0/G/NDATA/E']).toBeUndefined()
})

test('inserts new uns child only if parent is expanded', () => {
  let tree = mergeGraphNodes(emptyTree(), [node('acme', 'ENTERPRISE')])
  const closed = applyMqttToTree(tree, {
    topic: 'acme/plant1',
    payload: { a: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(closed.nodes['acme/plant1']).toBeUndefined()

  tree = { ...tree, expanded: ['acme'] }
  const open = applyMqttToTree(tree, {
    topic: 'acme/plant1',
    payload: { a: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(open.nodes['acme/plant1']?.payload).toEqual({ a: 1 })
  expect(open.childrenByParent['acme']).toContain('acme/plant1')
})
```

`feed-buffer.test.ts`:

```ts
import { expect, test } from 'vitest'
import { appendFeed, FEED_CAP, type FeedItem } from './feed-buffer'

function item(id: string): FeedItem {
  return { id, topic: `t/${id}`, timestamp: id, kind: 'uns', preview: { n: 1 } }
}

test('pause drops incoming', () => {
  const next = appendFeed([item('1')], item('2'), true)
  expect(next).toHaveLength(1)
  expect(next[0]?.id).toBe('1')
})

test('prepends newest and caps at 500', () => {
  const many = Array.from({ length: FEED_CAP }, (_, i) => item(String(i)))
  const next = appendFeed(many, item('new'), false)
  expect(next).toHaveLength(FEED_CAP)
  expect(next[0]?.id).toBe('new')
  expect(next.at(-1)?.id).toBe(String(FEED_CAP - 2))
})
```

`numeric-paths.test.ts`:

```ts
import { expect, test } from 'vitest'
import { getNumericPath, numericLeafPaths } from './numeric-paths'

test('flattens numeric leaves', () => {
  const paths = numericLeafPaths({ rpm: 10, nested: { temp: 3.2, name: 'x' }, tags: [{ v: 1 }, { v: 2 }] })
  expect(paths).toContain('rpm')
  expect(paths).toContain('nested.temp')
  expect(paths).toContain('tags[0].v')
  expect(paths).not.toContain('nested.name')
})

test('reads a numeric path', () => {
  expect(getNumericPath({ nested: { temp: 3.2 } }, 'nested.temp')).toBe(3.2)
  expect(getNumericPath({ tags: [{ v: 1 }] }, 'tags[0].v')).toBe(1)
  expect(getNumericPath({ rpm: 1 }, 'missing')).toBeUndefined()
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test
```

Expected: FAIL — modules not found / functions not defined.

- [ ] **Step 3: Implement the modules**

`src/lib/uns/sparkplug.ts`:

```ts
export const SPARKPLUG_PREFIX = 'spBv1.0/'

export function isSparkplugTopic(topic: string): boolean {
  return topic.startsWith(SPARKPLUG_PREFIX)
}
```

`src/lib/uns/payload.ts`:

```ts
export type ParsePayloadResult =
  | { ok: true; value: unknown }
  | { ok: false }

export function parseJsonPayload(data: unknown): ParsePayloadResult {
  if (data === null || data === undefined) {
    return { ok: false }
  }
  if (typeof data === 'object') {
    return { ok: true, value: data }
  }
  if (typeof data !== 'string') {
    return { ok: false }
  }
  try {
    return { ok: true, value: JSON.parse(data) }
  } catch {
    return { ok: false }
  }
}
```

`src/lib/uns/topics.ts`:

```ts
export function parentNamespace(namespace: string): string {
  const i = namespace.lastIndexOf('/')
  return i === -1 ? '' : namespace.slice(0, i)
}

export function childrenTopic(namespace: string): string {
  return namespace === '' ? '+' : `${namespace}/+`
}

export function historianTopic(namespace: string): string {
  return `${namespace}/#`
}

export function isFeedHighlight(topic: string, selected: string | null): boolean {
  if (!selected) {
    return false
  }
  return topic === selected || topic.startsWith(`${selected}/`)
}
```

`src/lib/uns/stale.ts`:

```ts
const FIVE_MINUTES_MS = 5 * 60 * 1000

export function isStale(lastUpdatedIso: string, nowMs: number): boolean {
  const then = Date.parse(lastUpdatedIso)
  if (Number.isNaN(then)) {
    return false
  }
  return nowMs - then > FIVE_MINUTES_MS
}
```

`src/features/tree/tree-model.ts`:

```ts
export type UnsNodeRecord = {
  nodeName: string
  nodeType: string
  namespace: string
  payload: unknown
  created: string
  lastUpdated: string
}

export type TreeState = {
  nodes: Record<string, UnsNodeRecord>
  childrenByParent: Record<string, string[]>
  expanded: string[]
  loading: Record<string, boolean>
  errors: Record<string, string>
}

export function emptyTree(): TreeState {
  return {
    nodes: {},
    childrenByParent: {},
    expanded: [],
    loading: {},
    errors: {},
  }
}

export function parentOf(namespace: string): string {
  const i = namespace.lastIndexOf('/')
  return i === -1 ? '' : namespace.slice(0, i)
}

function addChild(list: string[] | undefined, child: string): string[] {
  const next = list ?? []
  if (next.includes(child)) {
    return next
  }
  return [...next, child]
}

export function mergeGraphNodes(tree: TreeState, incoming: UnsNodeRecord[]): TreeState {
  const nodes = { ...tree.nodes }
  const childrenByParent = { ...tree.childrenByParent }
  for (const n of incoming) {
    nodes[n.namespace] = n
    const parent = parentOf(n.namespace)
    childrenByParent[parent] = addChild(childrenByParent[parent], n.namespace)
  }
  return { ...tree, nodes, childrenByParent }
}
```

`src/features/tree/tree-mqtt.ts`:

```ts
import { isSparkplugTopic } from '../../lib/uns/sparkplug'
import { parentOf, type TreeState, type UnsNodeRecord } from './tree-model'

export type MqttTreeEvent = {
  topic: string
  payload: unknown
  timestamp: string
}

export function applyMqttToTree(tree: TreeState, event: MqttTreeEvent): TreeState {
  if (isSparkplugTopic(event.topic)) {
    return tree
  }
  const existing = tree.nodes[event.topic]
  if (existing) {
    const patched: UnsNodeRecord = {
      ...existing,
      payload: event.payload,
      lastUpdated: event.timestamp,
    }
    return { ...tree, nodes: { ...tree.nodes, [event.topic]: patched } }
  }
  const parent = parentOf(event.topic)
  if (!tree.expanded.includes(parent)) {
    return tree
  }
  const leaf: UnsNodeRecord = {
    nodeName: event.topic.split('/').at(-1) ?? event.topic,
    nodeType: 'DEVICE',
    namespace: event.topic,
    payload: event.payload,
    created: event.timestamp,
    lastUpdated: event.timestamp,
  }
  const siblings = tree.childrenByParent[parent] ?? []
  const children = siblings.includes(event.topic) ? siblings : [...siblings, event.topic]
  return {
    ...tree,
    nodes: { ...tree.nodes, [event.topic]: leaf },
    childrenByParent: { ...tree.childrenByParent, [parent]: children },
  }
}
```

`src/features/feed/feed-buffer.ts`:

```ts
export const FEED_CAP = 500

export type FeedKind = 'uns' | 'sparkplug' | 'invalid-json'

export type FeedItem = {
  id: string
  topic: string
  timestamp: string
  kind: FeedKind
  preview: unknown | null
}

export function appendFeed(items: FeedItem[], next: FeedItem, paused: boolean): FeedItem[] {
  if (paused) {
    return items
  }
  const out = [next, ...items]
  return out.length > FEED_CAP ? out.slice(0, FEED_CAP) : out
}
```

`src/features/explore/numeric-paths.ts`:

```ts
export function numericLeafPaths(value: unknown, prefix = ''): string[] {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return prefix ? [prefix] : []
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, i) => numericLeafPaths(item, prefix ? `${prefix}[${i}]` : `[${i}]`))
  }
  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => {
      const path = prefix ? `${prefix}.${k}` : k
      return numericLeafPaths(v, path)
    })
  }
  return []
}

export function getNumericPath(value: unknown, path: string): number | undefined {
  const tokens = [...path.matchAll(/([^[.\]]+)|\[(\d+)\]/g)]
  let current: unknown = value
  for (const token of tokens) {
    if (token[1] !== undefined) {
      if (current === null || typeof current !== 'object' || Array.isArray(current)) {
        return undefined
      }
      current = (current as Record<string, unknown>)[token[1]]
    } else if (token[2] !== undefined) {
      if (!Array.isArray(current)) {
        return undefined
      }
      current = current[Number(token[2])]
    }
  }
  return typeof current === 'number' && Number.isFinite(current) ? current : undefined
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test
```

Expected: PASS (including Task 2 title test).

- [ ] **Step 5: Commit**

```bash
git add 10_frontend/src
git commit -m "Add UNS tree, feed, and payload domain rules with unit tests."
```

---

### Task 4: GraphQL URL, types, and operations

**Files:**
- Create: `10_frontend/src/lib/graphql/graphql-url.ts`, `10_frontend/src/lib/graphql/graphql-url.test.ts`, `10_frontend/src/lib/graphql/types.ts`, `10_frontend/src/lib/graphql/operations.ts`, `10_frontend/src/lib/graphql/client.ts`
- Modify: `10_frontend/src/app/types.ts` (create) if mapping lives here — keep GraphQL DTOs in `types.ts` only

**Interfaces:**
- Consumes: Vite `import.meta.env.DEV` / `VITE_GRAPHQL_URL`
- Produces: `getGraphqlHttpUrl()`, `getGraphqlWsUrl()`, `GraphqlConfigError`, `UNS_NODE_FIELDS` operations, Apollo `createApolloClient()`

- [ ] **Step 1: Write failing URL tests**

`graphql-url.test.ts`:

```ts
import { afterEach, expect, test, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

test('dev uses relative /graphql', async () => {
  vi.stubEnv('DEV', true)
  vi.stubEnv('PROD', false)
  const { getGraphqlHttpUrl } = await import('./graphql-url')
  expect(getGraphqlHttpUrl()).toBe('/graphql')
})

test('prod requires VITE_GRAPHQL_URL', async () => {
  vi.stubEnv('DEV', false)
  vi.stubEnv('PROD', true)
  vi.stubEnv('VITE_GRAPHQL_URL', '')
  const { getGraphqlHttpUrl, GraphqlConfigError } = await import('./graphql-url')
  expect(() => getGraphqlHttpUrl()).toThrow(GraphqlConfigError)
})

test('prod http url converts to ws', async () => {
  vi.stubEnv('DEV', false)
  vi.stubEnv('PROD', true)
  vi.stubEnv('VITE_GRAPHQL_URL', 'http://localhost:8000/graphql')
  const { getGraphqlWsUrl } = await import('./graphql-url')
  expect(getGraphqlWsUrl()).toBe('ws://localhost:8000/graphql')
})
```

Note: Vitest's `import.meta.env` is more reliable than `vi.stubEnv` for Vite flags. If `DEV` stubbing is flaky, test a pure helper instead:

```ts
export function resolveGraphqlHttpUrl(args: {
  prod: boolean
  envUrl: string | undefined
}): string {
  if (!args.prod) {
    return '/graphql'
  }
  const url = args.envUrl?.trim()
  if (!url) {
    throw new GraphqlConfigError('Missing VITE_GRAPHQL_URL for production build.')
  }
  return url
}

export function httpToWs(httpUrl: string): string {
  if (httpUrl.startsWith('https://')) {
    return `wss://${httpUrl.slice('https://'.length)}`
  }
  if (httpUrl.startsWith('http://')) {
    return `ws://${httpUrl.slice('http://'.length)}`
  }
  if (httpUrl.startsWith('/')) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}${httpUrl}`
  }
  return httpUrl
}
```

Write tests against `resolveGraphqlHttpUrl` and `httpToWs` (pass a fake location host for the relative case).

- [ ] **Step 2: Run tests — expect FAIL**

```bash
npm test -- src/lib/graphql/graphql-url.test.ts
```

- [ ] **Step 3: Implement URL helpers, types, operations, client**

`graphql-url.ts` — implement `GraphqlConfigError`, `resolveGraphqlHttpUrl`, `httpToWs`, and:

```ts
export function getGraphqlHttpUrl(): string {
  return resolveGraphqlHttpUrl({
    prod: import.meta.env.PROD,
    envUrl: import.meta.env.VITE_GRAPHQL_URL,
  })
}

export function getGraphqlWsUrl(): string {
  return httpToWs(getGraphqlHttpUrl())
}
```

`types.ts`:

```ts
export type GraphqlUnsNode = {
  nodeName: string
  nodeType: string
  namespace: string
  payload: { data: unknown } | null
  created: string
  lastUpdated: string
}

export type GraphqlHistoricalEvent = {
  publisher: string
  timestamp: string
  topic: string
  payload: { data: unknown } | null
}

export type GraphqlMqttMessage = {
  topic: string
  payload:
    | { __typename: 'JSONPayload'; data: unknown }
    | { __typename: 'BytesPayload'; data: string }
    | null
}
```

`operations.ts` (use `gql` from `@apollo/client`):

Install if not already: `npm install @apollo/client graphql graphql-ws`

```ts
import { gql } from '@apollo/client'

export const UNS_NODE_SELECTION = gql`
  fragment UnsNodeFields on UNSNode {
    nodeName
    nodeType
    namespace
    payload { data }
    created
    lastUpdated
  }
`

export const GET_UNS_NODES = gql`
  query GetUnsNodes($topics: [MQTTTopicInput!]!) {
    getUnsNodes(topics: $topics) {
      ...UnsNodeFields
    }
  }
  ${UNS_NODE_SELECTION}
`

export const GET_UNS_NODES_BY_PROPERTY = gql`
  query GetUnsNodesByProperty($propertyKeys: [String!]!, $topics: [MQTTTopicInput!]) {
    getUnsNodesByProperty(propertyKeys: $propertyKeys, topics: $topics) {
      ...UnsNodeFields
    }
  }
  ${UNS_NODE_SELECTION}
`

export const GET_HISTORIC_EVENTS = gql`
  query GetHistoricEvents($topics: [MQTTTopicInput!]!, $fromDatetime: DateTime, $toDatetime: DateTime) {
    getHistoricEventsInTimeRange(topics: $topics, fromDatetime: $fromDatetime, toDatetime: $toDatetime) {
      publisher
      timestamp
      topic
      payload { data }
    }
  }
`

export const MQTT_FEED = gql`
  subscription MqttFeed($topics: [MQTTTopicInput!]!) {
    getMqttMessages(topics: $topics) {
      topic
      payload {
        __typename
        ... on JSONPayload { data }
        ... on BytesPayload { data }
      }
    }
  }
`
```

If Strawberry names the node type differently than `UNSNode`, run:

```bash
cd 07_uns_graphql
uv run strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema
```

and align the fragment type name with the exported schema (do not add new backend types).

`client.ts`:

```ts
import { ApolloClient, HttpLink, InMemoryCache, split } from '@apollo/client'
import { GraphQLWsLink } from '@apollo/client/link/subscriptions'
import { getMainDefinition } from '@apollo/client/utilities'
import { createClient } from 'graphql-ws'
import { getGraphqlHttpUrl, getGraphqlWsUrl } from './graphql-url'

export function createApolloClient(): ApolloClient<unknown> {
  const httpLink = new HttpLink({ uri: getGraphqlHttpUrl() })
  const wsLink = new GraphQLWsLink(
    createClient({
      url: getGraphqlWsUrl(),
      retryAttempts: Infinity,
      shouldRetry: () => true,
    }),
  )
  const link = split(
    ({ query }) => {
      const def = getMainDefinition(query)
      return def.kind === 'OperationDefinition' && def.operation === 'subscription'
    },
    wsLink,
    httpLink,
  )
  return new ApolloClient({ link, cache: new InMemoryCache() })
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
npm test -- src/lib/graphql/graphql-url.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add 10_frontend/src/lib/graphql 10_frontend/package.json 10_frontend/package-lock.json
git commit -m "Add GraphQL URL rules, operations, and Apollo client."
```

---

### Task 5: App reducer and connection chip

**Files:**
- Create: `10_frontend/src/app/types.ts`, `10_frontend/src/app/connection.ts`, `10_frontend/src/app/connection.test.ts`, `10_frontend/src/app/uns-reducer.ts`, `10_frontend/src/app/uns-reducer.test.ts`, `10_frontend/src/app/UnsProvider.tsx`

**Interfaces:**
- Consumes: `TreeState`, `FeedItem`, `appendFeed`, `applyMqttToTree`, `mergeGraphNodes`, `parseJsonPayload`, `isSparkplugTopic`
- Produces: `UnsState`, `UnsAction`, `unsReducer`, `connectionChip(httpOk, wsOk)` → `'live' | 'degraded' | 'down'`

- [ ] **Step 1: Write failing tests**

`connection.test.ts`:

```ts
import { expect, test } from 'vitest'
import { connectionChip } from './connection'

test('connection chip', () => {
  expect(connectionChip(true, true)).toBe('live')
  expect(connectionChip(true, false)).toBe('degraded')
  expect(connectionChip(false, true)).toBe('degraded')
  expect(connectionChip(false, false)).toBe('down')
})
```

`uns-reducer.test.ts` — cover at least:

- `tree/load-ok` merges nodes
- `feed/mqtt` appends, patches tree, ignores Sparkplug for tree, drops when paused
- `ui/select-node` clears historical inspector
- `ui/select-historic-event` sets historical payload without changing `selectedNamespace`

Sketch:

```ts
import { expect, test } from 'vitest'
import { initialUnsState, unsReducer } from './uns-reducer'

test('paused feed does not grow', () => {
  let state = unsReducer(initialUnsState(), { type: 'feed/pause', paused: true })
  state = unsReducer(state, {
    type: 'feed/mqtt',
    topic: 'acme/l1',
    typename: 'JSONPayload',
    data: { rpm: 1 },
    timestamp: '2026-08-28T12:00:00Z',
  })
  expect(state.feed).toHaveLength(0)
})
```

Add tests for Sparkplug feed row `kind: 'sparkplug'` and UNS patch when the node already exists.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
npm test -- src/app
```

- [ ] **Step 3: Implement**

`connection.ts`:

```ts
export type ConnectionChip = 'live' | 'degraded' | 'down'

export function connectionChip(httpOk: boolean, wsOk: boolean): ConnectionChip {
  if (httpOk && wsOk) {
    return 'live'
  }
  if (httpOk || wsOk) {
    return 'degraded'
  }
  return 'down'
}

export function connectionLabel(chip: ConnectionChip, httpOk: boolean, wsOk: boolean): string {
  if (chip === 'live') {
    return 'Live'
  }
  if (chip === 'down') {
    return 'Down'
  }
  if (!httpOk && wsOk) {
    return 'Degraded — GraphQL queries down'
  }
  return 'Degraded — live feed down'
}
```

`uns-reducer.ts` — full implementation:

```ts
import { appendFeed, type FeedItem } from '../features/feed/feed-buffer'
import { applyMqttToTree } from '../features/tree/tree-mqtt'
import { emptyTree, mergeGraphNodes, type TreeState, type UnsNodeRecord } from '../features/tree/tree-model'
import { parseJsonPayload } from '../lib/uns/payload'
import { isSparkplugTopic } from '../lib/uns/sparkplug'

export type HistoricEventView = {
  topic: string
  timestamp: string
  publisher: string
  payload: unknown
}

export type UnsState = {
  tree: TreeState
  selectedNamespace: string | null
  historicEvent: HistoricEventView | null
  feed: FeedItem[]
  feedPaused: boolean
  httpOk: boolean
  wsOk: boolean
  treeBanner: string | null
}

export type UnsAction =
  | { type: 'tree/load-start'; parent: string }
  | { type: 'tree/load-ok'; parent: string; nodes: UnsNodeRecord[] }
  | { type: 'tree/load-err'; parent: string; message: string }
  | { type: 'tree/expand'; namespace: string }
  | { type: 'tree/collapse'; namespace: string }
  | { type: 'tree/banner'; message: string | null }
  | { type: 'ui/select-node'; namespace: string | null }
  | { type: 'ui/select-historic-event'; event: HistoricEventView | null }
  | { type: 'feed/pause'; paused: boolean }
  | {
      type: 'feed/mqtt'
      topic: string
      typename: 'JSONPayload' | 'BytesPayload' | 'unknown'
      data: unknown
      timestamp: string
      id?: string
    }
  | { type: 'conn/http'; ok: boolean }
  | { type: 'conn/ws'; ok: boolean }

export function initialUnsState(): UnsState {
  return {
    tree: emptyTree(),
    selectedNamespace: null,
    historicEvent: null,
    feed: [],
    feedPaused: false,
    httpOk: false,
    wsOk: false,
    treeBanner: null,
  }
}

function withExpanded(tree: TreeState, namespace: string): TreeState {
  if (tree.expanded.includes(namespace)) {
    return tree
  }
  return { ...tree, expanded: [...tree.expanded, namespace] }
}

export function unsReducer(state: UnsState, action: UnsAction): UnsState {
  switch (action.type) {
    case 'tree/load-start':
      return {
        ...state,
        tree: {
          ...state.tree,
          loading: { ...state.tree.loading, [action.parent]: true },
          errors: { ...state.tree.errors, [action.parent]: '' },
        },
      }
    case 'tree/load-ok':
      return {
        ...state,
        httpOk: true,
        treeBanner: action.parent === '' ? null : state.treeBanner,
        tree: {
          ...mergeGraphNodes(state.tree, action.nodes),
          loading: { ...state.tree.loading, [action.parent]: false },
          errors: { ...state.tree.errors, [action.parent]: '' },
        },
      }
    case 'tree/load-err':
      return {
        ...state,
        httpOk: false,
        treeBanner: action.parent === '' ? action.message : state.treeBanner,
        tree: {
          ...state.tree,
          loading: { ...state.tree.loading, [action.parent]: false },
          errors: { ...state.tree.errors, [action.parent]: action.message },
        },
      }
    case 'tree/expand':
      return { ...state, tree: withExpanded(state.tree, action.namespace) }
    case 'tree/collapse':
      return {
        ...state,
        tree: {
          ...state.tree,
          expanded: state.tree.expanded.filter((n) => n !== action.namespace),
        },
      }
    case 'tree/banner':
      return { ...state, treeBanner: action.message }
    case 'ui/select-node':
      return { ...state, selectedNamespace: action.namespace, historicEvent: null }
    case 'ui/select-historic-event':
      return { ...state, historicEvent: action.event }
    case 'feed/pause':
      return { ...state, feedPaused: action.paused }
    case 'conn/http':
      return { ...state, httpOk: action.ok }
    case 'conn/ws':
      return { ...state, wsOk: action.ok }
    case 'feed/mqtt': {
      const id = action.id ?? crypto.randomUUID()
      const sparkplug =
        action.typename === 'BytesPayload' || isSparkplugTopic(action.topic)
      if (sparkplug) {
        const row: FeedItem = {
          id,
          topic: action.topic,
          timestamp: action.timestamp,
          kind: 'sparkplug',
          preview: null,
        }
        return { ...state, feed: appendFeed(state.feed, row, state.feedPaused) }
      }
      const parsed = parseJsonPayload(action.data)
      if (!parsed.ok) {
        const row: FeedItem = {
          id,
          topic: action.topic,
          timestamp: action.timestamp,
          kind: 'invalid-json',
          preview: null,
        }
        return { ...state, feed: appendFeed(state.feed, row, state.feedPaused) }
      }
      const row: FeedItem = {
        id,
        topic: action.topic,
        timestamp: action.timestamp,
        kind: 'uns',
        preview: parsed.value,
      }
      return {
        ...state,
        feed: appendFeed(state.feed, row, state.feedPaused),
        tree: applyMqttToTree(state.tree, {
          topic: action.topic,
          payload: parsed.value,
          timestamp: action.timestamp,
        }),
      }
    }
  }
}
```

`tree/load-start` sets `loading[parent]=true` and clears that parent's error. Collapse keeps cached children. `ui/select-node` always clears `historicEvent`.

`UnsProvider.tsx`:

```tsx
import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react'
import { initialUnsState, unsReducer, type UnsAction, type UnsState } from './uns-reducer'

const StateCtx = createContext<UnsState | null>(null)
const DispatchCtx = createContext<Dispatch<UnsAction> | null>(null)

export function UnsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(unsReducer, undefined, initialUnsState)
  return (
    <StateCtx.Provider value={state}>
      <DispatchCtx.Provider value={dispatch}>{children}</DispatchCtx.Provider>
    </StateCtx.Provider>
  )
}

export function useUnsState(): UnsState {
  const s = useContext(StateCtx)
  if (!s) {
    throw new Error('useUnsState outside UnsProvider')
  }
  return s
}

export function useUnsDispatch(): Dispatch<UnsAction> {
  const d = useContext(DispatchCtx)
  if (!d) {
    throw new Error('useUnsDispatch outside UnsProvider')
  }
  return d
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
npm test -- src/app
```

- [ ] **Step 5: Commit**

```bash
git add 10_frontend/src/app
git commit -m "Add console state reducer and connection status rules."
```

---

### Task 6: Shell layout (header, routes, three columns)

**Files:**
- Create: `10_frontend/src/components/ui/button.tsx`, `10_frontend/src/components/ui/badge.tsx`, `10_frontend/src/features/shell/AppShell.tsx`
- Modify: `10_frontend/src/App.tsx`, `10_frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `useUnsState`, `connectionChip`, `connectionLabel`
- Produces: `AppShell` with nav links `/` (Home) and `/explore` (Explore); columns `tree` | `payload` | `context`; `Outlet` is not required if Home/Explore only swap the right pane via `useLocation`

- [ ] **Step 1: Extend App test**

Assert Home and Explore links exist, and a connection chip with text `Down` (default `httpOk`/`wsOk` false) or `Live` if you initialize both true — **initialize `httpOk` and `wsOk` to `false`** so first paint is `Down` until queries/subscriptions report in.

```tsx
expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
expect(screen.getByRole('link', { name: 'Explore' })).toHaveAttribute('href', '/explore')
expect(screen.getByText('Down')).toBeInTheDocument()
```

- [ ] **Step 2: Run test — expect FAIL** (links missing)

- [ ] **Step 3: Implement shell**

Minimal `button.tsx` / `badge.tsx` using `cn()` and Tailwind (`bg-console-panel`, borders `border-console-border`). Use `react-resizable-panels`:

```tsx
import { Link, useLocation } from 'react-router-dom'
import { Group, Panel, Separator } from 'react-resizable-panels'
```

(`Group` may be `PanelGroup` depending on library version — use `PanelGroup`, `Panel`, `PanelResizeHandle` from `react-resizable-panels`.)

`App.tsx`:

```tsx
import { ApolloProvider } from '@apollo/client'
import { Route, Routes } from 'react-router-dom'
import { UnsProvider } from './app/UnsProvider'
import { AppShell } from './features/shell/AppShell'
import { createApolloClient } from './lib/graphql/client'
import { GraphqlConfigError } from './lib/graphql/graphql-url'

const client = (() => {
  try {
    return createApolloClient()
  } catch (e) {
    return e
  }
})()

export function App() {
  if (client instanceof GraphqlConfigError) {
    return (
      <main className="p-8">
        <h1>Unified Namespace</h1>
        <p>{client.message}</p>
      </main>
    )
  }
  if (client instanceof Error) {
    throw client
  }
  return (
    <ApolloProvider client={client}>
      <UnsProvider>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={null} />
            <Route path="explore" element={null} />
          </Route>
        </Routes>
      </UnsProvider>
    </ApolloProvider>
  )
}
```

Prefer **not** nested routes: `AppShell` reads `useLocation().pathname === '/explore'` to render Explore vs Feed in the right column. Then `App` is:

```tsx
<ApolloProvider client={client}>
  <UnsProvider>
    <AppShell />
  </UnsProvider>
</ApolloProvider>
```

Wrap tests with `UnsProvider` + `MemoryRouter` + a mock ApolloProvider (`MockedProvider` from `@apollo/client/testing`). Add `@apollo/client/testing` — it ships with Apollo 3.

For Task 6, stub right/center panes as empty `<section aria-label="payload" />` etc. so later tasks fill them.

- [ ] **Step 4: `npm test` PASS; `npm run build` succeeds**

- [ ] **Step 5: Commit**

```bash
git commit -m "Add desktop console shell with Home and Explore chrome."
```

---

### Task 7: Lazy ISA-95 tree panel

**Files:**
- Create: `10_frontend/src/features/tree/TreePanel.tsx`, `10_frontend/src/features/tree/TreePanel.test.tsx`, `10_frontend/src/features/tree/useTreeQueries.ts`
- Modify: `AppShell.tsx` to render `TreePanel` in the left panel

**Interfaces:**
- Consumes: `GET_UNS_NODES`, `childrenTopic`, `mergeGraphNodes` via dispatch `tree/load-ok`, `isStale`
- Produces: expand/select UI; empty copy `No nodes yet — waiting for GraphQL / UNS data.`; banner retry for root load failure `Can't reach GraphQL`

- [ ] **Step 1: Component test with MockedProvider**

Mock `GetUnsNodes` with variable `topics: [{ topic: '+' }]` returning one enterprise `acme`. Render `TreePanel` inside `UnsProvider` + `MockedProvider`. Assert `acme` appears. Click to select — assert `aria-selected` or payload dispatch by checking a callback... easier: after click, `useUnsState().selectedNamespace === 'acme'`. Export a tiny `TreePanelHarness` in the test file that reads selected namespace.

Mock expand: after clicking expand on `acme`, a second mock with `topics: [{ topic: 'acme/+' }]` returns `acme/plant1`.

- [ ] **Step 2: Run test — FAIL**

- [ ] **Step 3: Implement `useTreeQueries` + `TreePanel`**

On mount: `dispatch({ type: 'tree/load-start', parent: '' })` then `client.query({ query: GET_UNS_NODES, variables: { topics: [{ topic: '+' }] } })`. Map GraphQL nodes through `parseJsonPayload` into `UnsNodeRecord` (if payload parse fails, `payload: null` and inspector will show `No payload.`).

On expand: if children not loaded (`childrenByParent[ns]` undefined), query `childrenTopic(ns)`. Always `dispatch({ type: 'tree/expand', namespace })`.

On collapse: `tree/collapse` only.

Root error: `conn/http ok: false`, `tree/banner` message `Can't reach GraphQL`, button Retry re-runs root query.

Chevron retry on branch error uses `errors[ns]`.

Dim row if `isStale(node.lastUpdated, Date.now())` via `opacity-50`.

Show relative time with `Intl.RelativeTimeFormat` or a small `formatRelative(iso)` helper in `tree-model.ts` (minutes/hours). Keep helper pure and unit-test one example if you add it.

Do not query `#`.

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "Load the ISA-95 tree one namespace level at a time."
```

---

### Task 8: Payload inspector

**Files:**
- Create: `10_frontend/src/features/payload/PayloadPanel.tsx`, `10_frontend/src/features/payload/PayloadPanel.test.tsx`
- Modify: `AppShell.tsx`

**Interfaces:**
- Consumes: `selectedNamespace`, `tree.nodes`, `historicEvent`
- Produces: node metadata + JSON; historical label `Historical event`; empty `Pick a node in the tree.`; missing `No payload.`

- [ ] **Step 1: Tests**

- No selection → `Pick a node in the tree.`
- Selected node with payload object → JSON text contains a known key
- `historicEvent` set → heading `Historical event`
- Node with `payload: null` → `No payload.`

Preload state by dispatching `tree/load-ok` and `ui/select-node` in the harness.

- [ ] **Step 2: FAIL then implement JSON as `<pre>{JSON.stringify(payload, null, 2)}</pre>`**

Tree click must `dispatch({ type: 'ui/select-historic-event', event: null })` so the node payload returns (do this in `TreePanel` select handler, not only in the reducer — also handle it in `ui/select-node` inside the reducer by setting `historicEvent: null`). **Prefer reducer:** `ui/select-node` always clears `historicEvent`. Then Task 5 test should assert that; add it there if missing.

- [ ] **Step 3: PASS and commit**

```bash
git commit -m "Show merged node payload and historical event JSON in the center pane."
```

---

### Task 9: Live MQTT feed and tree patches

**Files:**
- Create: `10_frontend/src/features/feed/FeedPanel.tsx`, `10_frontend/src/features/feed/FeedPanel.test.tsx`, `10_frontend/src/features/feed/useMqttFeed.ts`
- Modify: `AppShell.tsx` (Home right pane), `TreePanel` (click feed later from FeedPanel)

**Interfaces:**
- Consumes: `MQTT_FEED` with `topics: [{ topic: '#' }]`, `feed/mqtt` action, `isFeedHighlight`
- Produces: live rows; Pause control; Sparkplug badge `Sparkplug B (binary)`; invalid JSON label; highlight when topic matches selection; click UNS row selects/expands like search (Task 10 shares `expandToNamespace`)

Extract `expandToNamespace(dispatch, client, namespace)` in `src/features/tree/expand-to.ts` in this task so feed click and Explore click share it.

`expandToNamespace` algorithm:

```
segments = namespace.split('/')
prefix = ''
for segment of segments:
  parent = prefix
  prefix = prefix ? prefix + '/' + segment : segment
  if node prefix not in tree.nodes:
    query GET_UNS_NODES topics: [{ topic: childrenTopic(parent) }]
    dispatch tree/load-ok
  dispatch tree/expand parent  // expand parent so the child is visible
dispatch ui/select-node namespace
```

Load roots first if `childrenByParent['']` is empty.

- [ ] **Step 1: Feed row unit/component tests**

Test a presentational `FeedRow` (export from `FeedPanel.tsx` or `feed-row.tsx`):

- `kind: 'uns'` shows JSON preview
- `kind: 'sparkplug'` shows `Sparkplug B (binary)` and no `{`
- `kind: 'invalid-json'` shows `invalid JSON`
- `highlighted` sets `data-highlighted=true`

`useMqttFeed`: `useSubscription(MQTT_FEED, { variables: { topics: [{ topic: '#' }] }, onData, onError })`. `onData` dispatches `feed/mqtt` and `conn/ws ok: true`. `onError` / closed: `conn/ws ok: false`. `onComplete` treat as down.

- [ ] **Step 2: FAIL then implement FeedPanel with pause button dispatching `feed/pause`**

Autoscroll: if the list is scrolled to the top (newest first), keep scrollTop 0 on new items; if user scrolled down, do not jump.

Click Sparkplug row: no dispatch. Click UNS row: `expandToNamespace`.

- [ ] **Step 3: PASS and commit**

```bash
git commit -m "Subscribe to all MQTT traffic and patch visible tree nodes."
```

---

### Task 10: Explore search, historian, and numeric trend

**Files:**
- Create: `10_frontend/src/features/explore/ExplorePanel.tsx`, `10_frontend/src/features/explore/ExplorePanel.test.tsx`, `10_frontend/src/features/explore/useExploreQueries.ts`
- Modify: `AppShell.tsx` right pane when path is `/explore`
- Test: match-list click sets historian topic; empty search does not query; `from > to` disabled; empty range copy; trend dropdown from `numericLeafPaths`

**Interfaces:**
- Consumes: `GET_UNS_NODES`, `GET_UNS_NODES_BY_PROPERTY`, `GET_HISTORIC_EVENTS`, `historianTopic`, `expandToNamespace`, `getNumericPath`
- Produces: Explore right column UI

Search submit:

- If both topic and property keys empty, do not query; keep hint `Enter a topic or property.`
- Topic only: `GET_UNS_NODES` with `topics: [{ topic }]`
- Properties only: `GET_UNS_NODES_BY_PROPERTY` with `propertyKeys` (split comma/whitespace), `topics: null`
- Both: `GET_UNS_NODES_BY_PROPERTY` with `propertyKeys` and `topics: [{ topic }]`

Zero hits: `No nodes match.`

Match click: `expandToNamespace` + `ui/select-node` (reducer clears historic event).

Historian: when `selectedNamespace` is set, query `getHistoricEventsInTimeRange` with `topics: [{ topic: historianTopic(selectedNamespace) }]`, `fromDatetime`/`toDatetime` ISO from preset (15m/1h/24h) or custom inputs. Skip query if `from > to`.

Empty data: `No events in this range`, hide chart.

Table columns: timestamp, topic, publisher, payload preview. Row click: `ui/select-historic-event`.

Trend: union of `numericLeafPaths` across event payloads; `<select>` of paths; Recharts `LineChart` of `{ t: timestamp, v: getNumericPath(...) }` skipping undefined. No numeric fields → no chart.

`conn/http` true on successful query, false on historian error (show empty table message, no chart).

- [ ] **Step 1: Tests with MockedProvider** for search mapping and empty states

- [ ] **Step 2: FAIL, implement, PASS**

- [ ] **Step 3: Commit**

```bash
git commit -m "Add namespace search and historian trends on Explore."
```

---

### Task 11: Docker, compose, and README

**Files:**
- Create: `10_frontend/Dockerfile`, `10_frontend/nginx.conf`, `10_frontend/README.md`
- Modify: `docker-compose.yml` (add `uns_frontend` after `graphql_server`)

**Interfaces:**
- Consumes: Vite `dist`, `VITE_GRAPHQL_URL=http://localhost:8000/graphql` (browser-reachable, not Docker DNS)
- Produces: UI at `http://localhost:8088`, GraphQL still `http://localhost:8000`

- [ ] **Step 1: Add nginx config**

`10_frontend/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    include /etc/nginx/mime.types;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Dockerfile**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_GRAPHQL_URL=http://localhost:8000/graphql
ENV VITE_GRAPHQL_URL=$VITE_GRAPHQL_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 3: docker-compose service**

```yaml
  uns_frontend:
    build:
      context: ./10_frontend
      dockerfile: Dockerfile
      args:
        VITE_GRAPHQL_URL: http://localhost:8000/graphql
    ports:
      - "8088:80"
    depends_on:
      - graphql_server
```

- [ ] **Step 4: README** (`10_frontend/README.md`)

Document:

1. Start GraphQL (`docker compose up graphql_server` or local uvicorn on `8000`).
2. `cd 10_frontend && npm install && npm run dev` — Vite on 5173, proxy `/graphql` → 8000.
3. `npm test` / `npm run build`.
4. Compose UI: `http://localhost:8088` with `VITE_GRAPHQL_URL=http://localhost:8000/graphql`.
5. Trusted network, no login. CORS origins listed in Task 1.

- [ ] **Step 5: Commit**

```bash
git add 10_frontend/Dockerfile 10_frontend/nginx.conf 10_frontend/README.md docker-compose.yml
git commit -m "Ship the UNS console as a separate container next to GraphQL."
```

---

## Self-review (spec coverage)

| Spec requirement | Task |
| --- | --- |
| React SPA on GraphQL only | 2, 4, 9 |
| CORS + WS | 1 |
| Vite proxy `/graphql` | 2 |
| `VITE_GRAPHQL_URL` prod error | 4, 6 |
| Separate frontend container | 11 |
| Home / Explore shared shell, 3 resizable columns | 6 |
| Lazy `+` tree, cache, expand errors | 7 |
| Live patch / insert under expanded parent | 3, 5, 9 |
| No Sparkplug in tree; badge in feed | 3, 5, 9 |
| Feed cap 500, pause drops, `#` subscription | 3, 9 |
| Feed highlight; UNS click expands | 3, 9 |
| Search mapping + match list | 10 |
| Historian `ns/#`, presets, table, trend | 3, 10 |
| Historical event in center inspector | 5, 8, 10 |
| Connection Live/Degraded/Down | 5, 6 |
| Empty/error copy | 6–10 |
| Unit tests for domain | 3, 5 |
| Component tests feed/search/historian | 9, 10 |
| README | 11 |
| Out of scope (auth, OEE, Kafka, Playwright, BFF) | not planned |

No TBD placeholders. Action type strings in Task 5 are the contract for Tasks 7–10.
