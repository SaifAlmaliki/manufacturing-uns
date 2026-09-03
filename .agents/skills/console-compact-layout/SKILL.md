---
name: console-compact-layout
description: >-
  Applies the UNS console compact layout pattern — single app-header title, compact KPI
  chips, merged FilterToolbar rows, full-width PageContent, and no duplicate page banners.
  Use when the user asks to save UI space, compact KPIs, merge filter bars with tabs,
  reduce header layers, or apply the alarms-page layout to other routes (historian, system,
  sparkplug, streams, users, simulator, dashboard).
---

# Console compact layout

Goal: **maximize space for data**. Avoid stacking greeting + page title + description + KPI
grid + separate filter card. The alarms page (`AlarmManagementView`) is the reference.

## When to run

- User names this skill or asks for compact / space-efficient console UI
- A route still has `PageToolbar`, large `PageStat` grids, or tabs/search in separate rows
- A page repeats the app header (greeting + subtitle + in-page title block)

## Primitives (`11_frontend/src/components/ui/console-ui.tsx`)

| Component | Use for |
| --- | --- |
| `PageContent fullWidth` | Data-heavy routes — no `max-w-[1400px]` gutter |
| `PageStat compact` | KPI chips (~36px tall), not full cards |
| `CompactKpiRow` | KPI chips left, page actions right — **one row** |
| `FilterToolbar` | Tabs + search + selects + trailing buttons — **one row** |
| `SegmentTabs` | Primary sub-navigation only (e.g. Active / Rules / Audit) |
| `ConsoleCard` | Content panels — **not** page title banners |

Spacing defaults: `PageContent` uses `space-y-3`, padding `p-3 md:p-4 lg:px-6`.

## Header (`11_frontend/src/components/common/Header.tsx`)

- Route title lives in the **app header only** via `getPageHeading()`
- Feature routes (`/alerts`, `/historian`, `/system`, …): title only, **no subtitle**
- Dashboard/tree keep greeting + subtitle
- Header height: `h-14` — do not add a second title block in the view

When adding a new route, extend `getPageHeading()` with `{ title: 'Feature Name' }`.

## Page structure template

```tsx
<PageShell scroll={false} className="flex flex-col">
  <div className="min-h-0 flex-1 overflow-y-auto">
    <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
      {/* Optional: CompactKpiRow + actions */}
      {/* Primary SegmentTabs if the route has sub-views */}
      {/* FilterToolbar per tab — merged, not in ConsoleCard */}
      {/* Main content — tables, lists, embeds */}
    </PageContent>
  </div>
</PageShell>
```

Do **not** split header stats and body into separate scroll areas unless the embed
requires it (e.g. Grafana full-height).

## KPI row

```tsx
<CompactKpiRow actions={<>{/* BtnGhost, BtnPrimary, … */}</>}>
  <PageStat compact label="Critical" value={n} icon={…} />
  <PageStat compact label="Pending" value={n} icon={…} />
</CompactKpiRow>
```

Rules:

- Always `compact` on console KPI rows unless the user explicitly wants hero stats
- Never `grid grid-cols-4` of full-size `PageStat` cards on operational pages
- Put page actions in `CompactKpiRow` `actions`, not a separate toolbar card

## Filter bar

```tsx
<FilterToolbar
  tabs={{ items: [{ id: 'a', label: 'A' }], active, onChange }}
  search={{ value, onChange, placeholder: 'Search…' }}
  selects={[{ value, onChange, 'aria-label': 'Filter', options: [...] }]}
  trailing={<BtnSecondary>Export</BtnSecondary>}
/>
```

Rules:

- **One bar** — never `ConsoleCard` wrapping `SegmentTabs` beside a separate search row
- Sub-filters (role, severity) belong in `FilterToolbar`, not a second card
- Tab-only navigation (no search) may use `SegmentTabs` alone
- Search + selects without tabs: omit `tabs` prop (see `AlarmAuditLog`)

## Anti-patterns (remove on sight)

| Avoid | Replace with |
| --- | --- |
| `PageToolbar` / icon + title + description card | App header title only |
| `bg-white` / light-theme empty states | `ConsoleCard` dark tokens |
| `grid-cols-4` full `PageStat` | `CompactKpiRow` + `compact` |
| Nested `SegmentTabs` inside `ConsoleCard` + external search | `FilterToolbar` |
| Duplicate subtitle under header | Delete in-page description |
| `max-w-[1400px]` on wide data pages | `PageContent fullWidth` |
| `gap-4`/`gap-6` between every section | `gap-2`/`gap-3` |

## Route checklist

Apply in order for each view:

1. [ ] Add/update `getPageHeading()` entry — title only for feature routes
2. [ ] Remove in-page title banner (`PageToolbar`, icon+heading card)
3. [ ] Replace KPI grid with `CompactKpiRow` + `PageStat compact`
4. [ ] Merge filters into `FilterToolbar`
5. [ ] Set `PageContent fullWidth` where tables/lists need width
6. [ ] Collapse split header/body scroll unless required for embeds
7. [ ] Fix light-theme leftovers (`bg-white`, `dark:`-only styles)
8. [ ] Run `npm run build` in `11_frontend`

### Routes

| Route | View file | Status |
| --- | --- | --- |
| `/alerts` | `alarms/AlarmManagementView.tsx` | **Reference** |
| `/alerts` audit tab | `alarms/AlarmAuditLog.tsx` | FilterToolbar done |
| `/historian` | `explore/ExploreView.tsx` | Needs compact pass |
| `/system` | `system/SystemHealthView.tsx` | Needs compact pass |
| `/sparkplug` | `sparkplug/SparkplugView.tsx` | Needs compact pass |
| `/streams` | `streams/KafkaStreamsView.tsx` | Needs compact pass |
| `/users` | `users/UserManagementView.tsx` | Needs compact pass |
| `/simulator` | `simulator/SimulatorView.tsx` | Needs compact pass |
| `/dashboard` | `dashboard/DashboardView.tsx` | Review KPI density |

## Reference files

- `11_frontend/src/components/alarms/AlarmManagementView.tsx` — full pattern
- `11_frontend/src/components/alarms/AlarmAuditLog.tsx` — FilterToolbar without tabs
- `11_frontend/src/components/ui/console-ui.tsx` — primitives
- `11_frontend/src/components/common/Header.tsx` — `getPageHeading()`

## Verification

After changes, confirm visually:

- No duplicate titles between header and page body
- KPI row is a single slim band
- Filters share one bar with tabs/search
- Main content starts within ~120px of app header
- `npm run build` passes
