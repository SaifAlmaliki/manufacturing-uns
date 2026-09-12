# Task 14 Report: Edge-aware connectivity console

**Branch:** `feat/cloud-platform-outbound-edge` (base `49ca5418`)  
**Commit:** `4af17eb2` — `feat(console): add edge-aware connectivity panel and status`  
**Status:** Complete

## Delivered

| Artifact | Path |
| --- | --- |
| Edge status helpers | `11_frontend/src/lib/connectivity/edge-status.ts`, `edge-status.test.ts` |
| Async job polling | `11_frontend/src/lib/connectivity/edge-jobs.ts`, `edge-jobs.test.ts` |
| Edge devices panel | `11_frontend/src/components/connectivity/EdgeDevicesPanel.tsx`, `EdgeDevicesPanel.test.tsx` |
| Cloud-aware connectivity UI | `ConnectivityView.tsx`, `BrowseDataDrawer.tsx`, `SignalsTab.tsx`, `SignalContextPanel.tsx` |
| GraphQL client/types/queries | `11_frontend/src/services/graphql/{client,types,queries}.ts` |
| Protocol mapping/validation | `map-servers.ts`, `validate-server.ts`, `host-port.ts` + tests |

## Behavior

- Cloud edge mode activates when `getEdgeDevices()` returns devices; browser never opens OPC UA/Modbus to DMZ hosts.
- `EdgeDevicesPanel` shows compact KPIs (desired/applied revision lag, connection health, heartbeat staleness) and phase labels: `waiting_for_routes`, `pending`, `applying`, `applied`, `failed`, `degraded`.
- Admin: register edge, one-time enrollment token dialog (in-memory only, no `localStorage`), revoke device.
- Engineer: grant/revoke edge access without seeing secrets.
- Server saves use `edgeId` + `expectedRevision`; save success copy explicitly does not imply live connection.
- Browse/test in cloud mode enqueue edge jobs (`browseOpcUaTags`, `testConnectivityServer` → `getConnectivityJob`); browse generation guard prevents stale results overwriting edited tags/topics.
- Live values use central MQTT subscriptions; Modbus unit ID and protocol capability gating added.
- Simulation sites labeled via registered edge name; UI copy distinguishes fixtures from real PLCs.

## Verification

```
cd 11_frontend
npm run test:run -- src/components/connectivity src/lib/connectivity
npm run lint
```

| Check | Result |
| --- | --- |
| Test files | 9 passed |
| Tests | 107 passed |
| Lint (`tsc --noEmit`) | Clean |

## Task 11A walkthrough (cloud console)

Operator flow documented in `docs/operations/edge-simulation-demo.md`; console supports:

1. Enroll simulation edge by registered name (e.g. edge-sim profile from Task 11A).
2. Observe `pending` → `applying` → `applied` as desired/applied revisions converge.
3. Configure both simulated industrial connections (OPC UA + Modbus) scoped to selected edge.
4. View central live MQTT values on Signals tab without browser DMZ connectivity.
5. Change a topic mapping and confirm `expectedRevision` optimistic write + revision lag KPI.

Live VM-to-cloud evidence (screenshots, broker counters) remains operator-owned per Task 11A report.

## Concerns

1. `getConnectivityServers` list may not hydrate all edge status fields; panel merges `getEdgeDevices` KPIs separately.
2. `act(...)` warnings in `SignalsTab` tests are pre-existing noise, not failures.
3. Task 11A end-to-end walkthrough not executed in this session against a running cloud stack.
