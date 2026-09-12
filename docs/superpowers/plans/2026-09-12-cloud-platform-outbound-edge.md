# Cloud Platform and Outbound DMZ Edge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> to implement task-by-task. Use `superpowers:subagent-driven-development` only
> if the user explicitly requests delegation. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deploy the central UNS on Hostinger VPS or AWS, with securely enrolled
HiveMQ Edge VMs that initiate all cloud connections and receive remotely authored
configuration through a local management agent. Demonstrate the complete loop
without physical PLCs using an optional simulator profile on the edge VM.

**Required capability:** The released implementation must connect to real PLC/SCADA
endpoints as well as simulators. Both use the same HiveMQ Edge adapters, cloud
configuration workflow, agent, and upstream pipeline. Simulation is an optional
test-source deployment, not a substitute for real-device connectivity.

**Architecture:** Separate MQTT/TLS upstream data from HTTPS desired-state
management. Extend the existing connectivity catalog with edge ownership and
versioned reconciliation. Retain MQTT → canonical Kafka → independent consumers;
add a durable HTTPS-to-MQTT outbox for business publishers that cannot use MQTT.

**Tech Stack:** Existing Python 3.14, FastAPI/Strawberry, SQLAlchemy/Alembic,
PostgreSQL/Timescale, MQTT/Paho, Kafka, React/TypeScript, pytest/Vitest, HiveMQ Edge,
production central MQTT broker, Linux/OCI/Compose, TLS/mTLS, S3-compatible storage.

---

Design: [Cloud-hosted UNS with outbound-only DMZ management](../specs/2026-09-12-cloud-platform-outbound-edge-design.md).

Status: Code deliverables for Tasks 1–16 are on `feat/cloud-platform-outbound-edge`.
Qualification remains `unqualified` until operator licenses, digest-pinned images, and
live VM/cloud runs complete. See [cloud-edge-qualification.md](../../benchmarks/cloud-edge-qualification.md) §14.

Related: [ADR-0012](../../adr/0012-multi-system-uns-to-lake-delivery.md),
[existing delivery plan](2026-09-11-multi-system-uns-to-lake.md),
[existing delivery runbook](../../operations/uns-to-lake-delivery.md).

## Delivery order and execution rules

Deliver this programme as independently verified milestones:

1. **Cloud/data foundation:** qualification, reproducible infrastructure, secure
   central MQTT, existing raw-lake compatibility (Tasks 1, 2, 10, 12).
2. **Remote edge configuration:** contracts, catalog, identity, agent, console,
   and installable DMZ package, including hardware-free commissioning
   (Tasks 3–9, 11, 11A, 14).
3. **Business push integration:** generic HTTPS ingress/outbox plus direct MQTT
   publication contracts (Task 13). Native vendor connectors are separate projects.
4. **Operational qualification:** canary, failures, restore, and handoff (Tasks 15–16).

Tasks are listed in dependency order for execution in one session. Do not run a
later task merely because a milestone lists it. Infrastructure qualification may
proceed independently of contract work; no delegation is implied.
Task 11A's package/fixture work follows Task 11; its full cloud-console walkthrough
finishes with Task 15 after Tasks 12 and 14 are available.

- Re-read `AGENTS.md`, installed dependencies, and current diffs before execution.
  Only `console-compact-layout` existed under repository `.agents/skills/` during
  drafting; do not claim absent skills were loaded. Use available applicable skills.
- The working tree already contains extensive staged delivery and UI work. Preserve
  it. The old plan's unchecked boxes are not proof that its code is absent.
- Use TDD for behavior changes: write the named contract tests, run for the expected
  missing/incorrect behavior, implement the smallest change, then rerun. A missing
  service, license, dependency, or credential is a blocked test, not a passing one.
- Python commands below run from repository root with `-n 0`. Frontend commands
  name `11_frontend` as their working directory. Linux installation commands are
  future operator commands, not commands to run on this Windows authoring machine.
- Refresh official version-specific docs for HiveMQ APIs/bridging, TLS, container
  runtime, identity server, cloud providers, and client delivery callbacks. Context7
  authentication failed during drafting; direct primary sources are in the design.
- No live fault injection, purchases, automatic production migrations, offset resets,
  deleting persistent volumes, commit, or push without explicit authorization.
- Kubernetes/HA, a second PLC collector, arbitrary remote execution, process control,
  generic reverse proxying into OT, transformations, and native SAP/LIMS/MES connector
  implementations are outside these deliverables.
- The optional `edge-sim` profile is an explicit part of the edge release. Reuse
  current OEE and multi-system MQTT generators and add OPC UA/Modbus test servers;
  do not require physical PLCs or deploy these test sources in the cloud stack.
- Real-device-ready OPC UA/Modbus support is mandatory even while physical hardware
  is unavailable. Keep endpoint/security/node/register/polling settings configurable;
  preserve qualified S7/EtherNet/IP support. Real and simulated connections can
  coexist. Do not hardcode fixture hosts, values, nodes, or register maps into adapters
  or cloud forms, or require the simulation overlay for the base stack to operate.

## File responsibilities

All new paths below are proposed files, not claims that they already exist.

| Boundary | Existing paths | New paths |
| --- | --- | --- |
| Pure edge contracts | `00_uns_config/src/uns_config/` | `edge_contracts.py`, `edge_config_digest.py` |
| Desired state and leases | `09_uns_model/src/uns_model/connectivity.py`, `tables.py` | `edge_tables.py`, `edge_repository.py`, `edge_secrets.py` |
| Database evolution | `09_uns_model/migrations/` | Versioned edge-management and business-outbox migrations |
| Edge management API | `07_uns_graphql/src/uns_graphql/uns_graphql_app.py` | `edge_api/{router,identity,enrollment,issuer,service,jobs}.py` |
| Console integration | Existing connectivity mutations, queries, input/types and auth | `mutations/edge.py`, `queries/edge.py`, `type/edge.py` |
| Edge runtime | `00_uns_config/src/uns_config/hivemq_edge_api.py` as reference | `15_uns_edge_agent/src/uns_edge_agent/{main,config,cloud_client,enrollment,journal,reconcile,edge_client,credentials,jobs,health_check}.py` |
| Protocol compilation | Existing Edge API/XML inputs and connectivity enums | `15_uns_edge_agent/src/uns_edge_agent/protocols/{registry,opcua,modbus,s7,eip}.py` |
| Business HTTP ingress | `publications.py`, `publication_routes.py` | `07_uns_graphql/src/uns_graphql/publication_api/{router,service,worker}.py`; `09_uns_model/src/uns_model/publication_outbox.py` |
| Delivery/install artifacts | Existing Dockerfiles, config loaders | `deploy/cloud/`, `deploy/edge/`, `deploy/test/`, `.github/workflows/cloud-edge-release.yml` |
| Edge simulation | `HiveMQ-Simulator.sh`, `conf/simulator/Dockerfile`, `multi_system_publishers.py`, `Dockerfile.multi-system` | `deploy/edge/compose.simulation.yml`, `deploy/edge/simulation/`; `conf/simulator/protocols/`; `docs/operations/edge-simulation-demo.md` |
| Console | `11_frontend/src/components/connectivity/`, `services/graphql/` | `EdgeDevicesPanel.tsx`, `lib/connectivity/edge-status.ts` |
| Operations | Existing UNS-to-lake runbook | `docs/operations/cloud-platform.md`, `dmz-edge-installation.md`, `business-publisher-onboarding.md` |
| Evidence | Existing delivery benchmarks | `docs/benchmarks/cloud-edge-qualification.md` |

Do not place runtime agent code in `13_uns_factory_agent`; that is a different
existing platform component. The new agent does not depend on PostgreSQL, Kafka,
the model repository, or the cloud GraphQL runtime.

## Task 1: Freeze baseline and qualify product boundaries

**Files:** Read `docker-compose.yml`, `conf/hivemq/config.xml`, existing delivery
runbook/benchmark, and the API/connection files listed in the design. Create
`docs/benchmarks/cloud-edge-qualification.md` and `deploy/release-contract.json`.

- [ ] Run `git status --short`, `git diff --stat`, `git diff --cached --stat`, and
  `git log --oneline -10` independently. Record the starting staged changes.
- [ ] Run `graphify query "hivemq_edge_api connectivity OPC UA deployment" --budget 2000`.
  Confirm the returned source paths, all direct PLC calls, all config writers, and
  current MQTT command/Sparkplug rebirth publishers. Record which are disabled in
  the new edge-to-cloud-only profile.
- [ ] Verify current v1/v2 readers and lake tests against the existing delivery
  plan. Record actual readiness, not its old "ready for implementation" heading.
- [ ] Record a candidate central **full HiveMQ broker** edition/image digest,
  authentication extension, Edge version/digest, offline-buffering license, and
  supported adapter API schemas. Obtain operator license input; no purchase.
- [ ] Qualify mTLS, publish-only edge ACLs, active-session revocation, stable client
  IDs, retained flags, persistent subscriptions, queue limits, and broker restart
  behavior. If the candidate cannot pass, stop the production broker branch and
  request a product/edition decision; do not silently substitute a broker.
- [ ] Define `release-contract.json` as a deployment validator input with
  `release_id`, `images` (name/digest), `edge_api_version`, `supported_protocols`,
  `buffering_license_required`, `broker_profile`, and `qualification_status`.
  Status values are `unqualified`, `qualified`, `failed`. Unqualified manifests
  can run only in the explicit isolated qualification profile.
- [ ] Record the measured/accepted RPO separately for edge power loss, broker power
  loss, canonical Kafka persistence, and SQL outbox persistence. No overall zero-loss
  claim from MQTT QoS alone. License absence blocks the durable edge tier, not writing
  unit tests for the management agent.

**Exit:** Source baseline and product assumptions are explicit; infrastructure
version/API/license facts are recorded or visibly blocked.

## Task 2: Isolated cloud/DMZ/OT acceptance harness

**Create:** `deploy/test/compose.yml`, `deploy/test/firewall-rules.sh`,
`deploy/test/conftest.py`, `deploy/test/test_network_boundary.py`,
`deploy/test/test_cloud_edge_pipeline.py`, `deploy/test/test_release_contract.py`.

- [ ] Build a fixture with isolated cloud, DMZ, and OT networks, a stateful test
  router/firewall, test CAs, an OPC UA simulator, a Modbus simulator, and the existing
  canonical/lake fixture. No service uses production credentials or volumes.
- [ ] Share the protocol test servers and current MQTT publisher images with Task
  11A's deployable edge simulation profile. CI must exercise the same source images
  shipped to the DMZ VM, not unrelated fakes that cannot be installed there.
- [ ] Define the `cloud_edge` fixture methods and their results explicitly:

```text
cloud_can_open_dmz_management() -> bool
enroll(edge_id) -> enrolled identity
save_connection(edge_id, protocol, settings) -> revision
wait_applied(edge_id, revision, timeout) -> verified report
publish_case(application, site, body) -> expected event identity
wait_lake(identity, timeout) -> physical rows including duplicates
block_cloud(), restore_cloud(), restart_edge(), restart_broker()
```

- [ ] Write the first network contract. The fixture must prove its negative check
  actually targets a listening private API, not a nonexistent destination.

```python
def test_cloud_cannot_dial_dmz_management(cloud_edge):
    assert cloud_edge.local_management_is_healthy()
    assert not cloud_edge.cloud_can_open_dmz_management()
```

`local_management_is_healthy()` is an agent-side/private-network API probe. Include
packet capture/connection counters proving edge initiation and established replies.

- [ ] Run `uv run pytest deploy/test/test_network_boundary.py -n 0 -v`; expect the
  first behavior failure until network rules are implemented. Report unavailable
  Linux container networking as a prerequisite.
- [ ] Implement the fixture and assert both cloud-facing connections work outbound,
  unsolicited inbound connections fail, and OT connectivity requires its own rule.
- [ ] Rerun the command. Tests must use timeouts and print pending revisions, offsets,
  certificate subjects, and firewall counters without secrets.

## Task 3: Pure edge contracts and deterministic snapshots

**Create:** `00_uns_config/src/uns_config/edge_contracts.py`, `edge_config_digest.py`,
`00_uns_config/test/test_edge_contracts.py`, `test_edge_config_digest.py`.

- [ ] Define the public pure functions/types below. Use frozen dataclasses and
  explicit JSON validation; no database, MQTT, HTTP, or environment imports.

```text
AdapterConfig(adapter_id, protocol, connection, tags, northbound_mappings)
EdgeConfig(contract_version, edge_id, revision, digest, adapters,
           required_route_revision, secret_refs, deleted_adapter_ids)
EdgeReport(edge_id, boot_id, report_sequence, desired_revision, applied_revision,
           applied_digest, phase, adapter_results, last_error_code, versions, capabilities)
decode_edge_config(raw: bytes) -> EdgeConfig
canonical_config_bytes(document: dict) -> bytes
configuration_digest(document: dict) -> str
validate_collection_only(config: EdgeConfig) -> None
```

- [ ] Write deterministic encoding and command-rejection tests:

```python
def test_digest_is_independent_of_object_key_order():
    from uns_config.edge_config_digest import configuration_digest
    assert configuration_digest({"revision": 2, "edge_id": "edge-01"}) == (
        configuration_digest({"edge_id": "edge-01", "revision": 2})
    )
```

Add explicit cases for NaN, duplicate JSON keys, unknown contract version, missing
edge ID, boolean-as-revision, oversized raw document, excessive adapter/tag counts,
southbound mappings, write-enabled protocol settings, and undeclared deletion.

- [ ] Run `uv run --package uns_config pytest 00_uns_config/test/test_edge_contracts.py 00_uns_config/test/test_edge_config_digest.py -n 0 -v`.
- [ ] Implement canonical UTF-8 JSON using sorted keys, compact separators,
  `allow_nan=False`, and exclusion of only the top-level digest. Validate the 4 MiB,
  500-adapter, and 20,000-tag ceilings before constructing large secondary objects.
- [ ] Rerun the tests. Round-trip all first-release protocol fixtures and prove
  secret values cannot appear in the public desired-state representation.

## Task 4: Edge catalog, concurrency, secret storage, and migrations

**Modify:** `09_uns_model/src/uns_model/tables.py`, `connectivity.py`, `cli.py`.
**Create:** `edge_tables.py`, `edge_repository.py`, `edge_secrets.py` in that package;
`09_uns_model/migrations/versions/0010_edge_management.py`;
`09_uns_model/test/test_edge_repository.py`, `test_edge_secrets.py`,
`test_edge_migration.py`.

- [ ] Inspect the real Alembic head (drafting baseline: `0009_historian_event_pipeline.py`);
  use the next free filename if `0010` has been occupied and set `down_revision` accordingly.
  Add tables for devices, user grants, enrollment attempts, certificates, immutable
  configurations, reports, management leases, secret versions, jobs, and audit events.
  Add nullable `edge_id` to legacy connectivity rows for migration only.
- [ ] Define `EdgeRepository.save_desired(edge_id, expected_revision, document)`,
  `latest_desired(edge_id)`, `accept_report(identity, lease, report)`,
  `acquire_lease(edge_id, boot_id)`, and `assign_legacy(connection_id, edge_id)`.
  All reads/writes take explicit edge scope. New cloud-mode connections require it.
- [ ] Write SQL-backed tests: two editors at revision 3 cannot both create revision
  4; a connection edit/snapshot rollback together; edge A cannot read/report for B;
  a stale lease/report cannot mark a new revision applied; legacy rows remain
  unassigned until an explicit assignment.

```text
save expected=3 -> revision=4
second save expected=3 -> revision_conflict, no partial catalog write
apply report revision=3 while desired=4 -> desired stays 4, report remains historical
report with revoked lease -> rejected, current status unchanged
```

- [ ] Run `uv run --package uns_model pytest 09_uns_model/test/test_edge_repository.py 09_uns_model/test/test_edge_secrets.py 09_uns_model/test/test_edge_migration.py -n 0 -v`.
- [ ] Implement a row lock/compare-and-swap per edge, immutable unique revisions,
  monotonic lease generations, and bounded report retention. Store detailed reports
  for 30 days while retaining latest applied state and audit references.
- [ ] Encrypt connection secrets with authenticated encryption using explicit
  versioned key IDs, fresh nonces, and edge/secret/version as associated data. Test
  wrong-key, wrong-edge, tampering, rotation, and redacted serialization. Persist key
  material outside SQL; document encrypted backups/key recovery.
- [ ] Rerun tests plus `uv run --package uns_model pytest 09_uns_model/test/test_connectivity.py -n 0 -v`.
  Ensure migration execution works from the release image including packaged
  Alembic files; current CLI discovers them in the editable source tree.

## Task 5: Enrollment, certificate lifecycle, and cloud management API

**Create:** `07_uns_graphql/src/uns_graphql/edge_api/__init__.py`, `router.py`,
`identity.py`, `enrollment.py`, `issuer.py`, `service.py`;
`07_uns_graphql/test/edge_api/test_enrollment.py`, `test_identity.py`,
`test_configuration_api.py`.
**Modify:** `uns_graphql_app.py`, `07_uns_graphql/pyproject.toml` for explicit
cryptography/runtime dependencies, and applicable lockfiles.

- [ ] Expose typed REST routes alongside the existing GraphQL router:

| Method/path | Contract |
| --- | --- |
| `POST /api/edge/v1/enroll` | Single-use token and two CSRs; returns authorized certificate chains and bootstrap identity. |
| `POST /api/edge/v1/session` | mTLS identity + boot ID obtains a fenced lease. |
| `GET /api/edge/v1/configuration` | Identity-derived edge scope; full snapshot with digest/ETag, or 304. Requires active lease. |
| `POST /api/edge/v1/reports` | Idempotent report; reject stale lease/unknown revision/digest mismatch. |
| `GET /api/edge/v1/secrets/{secret_id}/{version}` | Only versions referenced by that edge's authorized snapshot. |
| `POST /api/edge/v1/renew` | Same-identity CSR renewal with overlapping validity. |

- [ ] Write tests for expired/reused enrollment, parallel consumption, same-CSR
  response-loss retry, different-CSR retry, forged identity header, wrong certificate
  purpose, revoked device, public-backend bypass, and scope tampering.
- [ ] Run `uv run --package uns_graphql pytest 07_uns_graphql/test/edge_api -n 0 -v`.
- [ ] Implement token hashing and transactionally reserved CSR digests. Issue only
  server-derived subjects/EKUs under a restricted intermediate. Keep issuance out
  of ordinary GraphQL resolver logic; inject issuer and clock in tests.
- [ ] Implement private trusted-proxy identity verification and record checks on
  each request. Strip untrusted identity headers at the proxy and prohibit direct
  public backend access in deployment tests. Enrollment is rate/body limited.
- [ ] Implement 30-day certificates, renewal at day 20, 24-hour overlap, explicit
  revoke, and no expired-identity fallback. mTLS management and MQTT private keys
  never leave the agent; only certificate material travels from the issuer.
- [ ] Rerun API tests. Verify correct errors: 401 for absent/invalid identity, 403
  for scope/revocation, 409 for revision/lease conflicts, 413 for body bounds, 429
  for rate limits, and 503 for unavailable durable dependencies.

## Task 6: Standalone agent package, durable journal, and poll loop

**Create:** `15_uns_edge_agent/pyproject.toml`, `README.md`, `Dockerfile`;
`15_uns_edge_agent/src/uns_edge_agent/{__init__,main,config,cloud_client,enrollment,journal,credentials,health_check}.py`;
`15_uns_edge_agent/test/{conftest,test_journal,test_polling,test_enrollment,test_credentials}.py`.
**Modify:** root `pyproject.toml`/`uv.lock` and package source mappings as needed.

- [ ] Register distribution `uns_edge_agent` and console scripts `uns_edge_agent`,
  `uns_edge_enroll`, and `uns_edge_healthcheck`. Depend on `uns_config`, an HTTP
  client, and cryptography directly, not the cloud model/GraphQL packages.
- [ ] Define `Journal.begin_apply(config, recovery_snapshot)`, `finish_apply(report)`,
  `pending_apply()`, `pending_reports()`, and `ack_report(sequence)`. Use a local
  transactional SQLite journal with durable synchronization and a process lock;
  it contains management state only, not a telemetry spool.
- [ ] Add restart tests: intent survives process exit; report retries keep the same
  boot ID/sequence/content; same revision/digest is safe; a second active local
  process cannot acquire the journal lock.
- [ ] Run `uv run --package uns_edge_agent pytest 15_uns_edge_agent/test/test_journal.py 15_uns_edge_agent/test/test_polling.py 15_uns_edge_agent/test/test_enrollment.py 15_uns_edge_agent/test/test_credentials.py -n 0 -v`.
- [ ] Implement an injected-clock poll loop with 15-second jittered polling,
  30-second heartbeat, request/connect timeouts, ETags, a five-minute backoff cap,
  and graceful shutdown. A transient HTTPS outage does not stop HiveMQ collection.
- [ ] Generate keys locally, enroll without echoing the token, atomically install
  credential files, and erase temporary enrollment material. Store MQTT key material
  in the pinned Edge version's supported keystore format; test Edge readability.
- [ ] Implement reconnect/lease recovery after agent restart without accepting
  out-of-order reports from older sessions. Use a 120-second renewable lease; reject
  takeover while live except an explicit admin recovery action. Stop starting local
  applies if lease renewal fails; replacement owners read actual state because an
  old in-flight local API call is not remotely fenced by SQL. Bound unsent reports by keeping durable
  terminal apply reports and coalescing superseded heartbeat-only entries.
- [ ] Rerun the four suites. Health distinguishes a live process, authenticated cloud
  connectivity, journal availability, and local Edge API reachability.

## Task 7: Protocol adapters and crash-aware local application

**Create:** agent `edge_client.py`, `reconcile.py`, `protocols/__init__.py`,
`protocols/registry.py`, `protocols/opcua.py`, `protocols/modbus.py`,
`protocols/s7.py`, `protocols/eip.py`;
`15_uns_edge_agent/test/test_protocols.py`, `test_reconcile.py`, `test_edge_api_contract.py`.
**Read:** existing `hivemq_edge_api.py`, `hivemq_edge_xml.py`; reuse pure logic only
after removing assumptions about global catalog lists and default credentials.

- [ ] Define the narrow runtime contract:

```text
EdgeClient.capabilities() -> versioned adapter schemas/capability list
EdgeClient.read_owned(edge_id) -> normalized adapter configuration
EdgeClient.apply_adapter(compiled_adapter) -> None
EdgeClient.delete_owned(adapter_id) -> None
compile_adapter(AdapterConfig, capabilities, resolved_secrets) -> API operations
Reconciler.apply(EdgeConfig) -> EdgeReport
```

- [ ] Create versioned OPC UA and Modbus TCP fixtures from the qualified API schemas.
  OPC UA includes endpoint, security policy/mode, credentials/certificates, node IDs,
  sampling and mappings. Modbus includes host/port, unit ID, address/function/type,
  byte/word order, polling and mappings. Validate numeric ranges and source semantics;
  do not squeeze Modbus addresses into an OPC UA node field.
- [ ] Add real-device configuration contracts alongside fixture cases: non-fixture
  endpoint hostnames/IPs and ports, secured OPC UA settings, different node IDs,
  Modbus unit IDs/register maps/scaling and polling intervals. Assert the compiled
  operations preserve the owner's settings, subject to the local allowlist. Use
  protocol test servers with alternate configurations to execute these contracts
  without claiming they constitute physical-device qualification.
- [ ] Test that production modules do not import simulator code, the base deployment
  can manage connections without the simulation overlay, and a mixed catalog keeps
  each real-shaped/simulated connection's identity, configuration, and topic ownership
  separate. Use the same adapter compilation/application path for both.
- [ ] Add tests with a fake local API that can fail at adapter, tags, mappings,
  readback, and delete stages. The fake records actual applied state independently
  of requests, and supports failure after a write succeeds but before its response.

```text
revision 8 applied -> attempt 9 -> mappings fail
recovery readback equals revision 8 -> report failed, applied_revision remains 8
recovery also fails -> report degraded with per-adapter actual state
restart during apply -> recover from journal, never report 9 merely from intent
```

- [ ] Run `uv run --package uns_edge_agent pytest 15_uns_edge_agent/test/test_protocols.py 15_uns_edge_agent/test/test_reconcile.py -n 0 -v`.
- [ ] Implement full validation before writes, one apply at a time, normalized
  readback, explicit ownership, create/update before explicit deletions, and bounded
  recovery. Empty/corrupt response cannot delete adapters. Preserve unmanaged IDs.
- [ ] Reject unsupported protocols, southbound mappings, changed bootstrap broker
  destination, endpoints outside the IT-owned allowlist, and invalid secret scope.
  Resolve/check actual destination addresses, not just display names; retain OT
  firewall enforcement as the network boundary.
- [ ] Run the tests again, then `uv run --package uns_edge_agent pytest 15_uns_edge_agent/test/test_edge_api_contract.py -n 0 -v`
  against a licensed/pinned isolated Edge instance. Verify configuration persists
  after both container and VM restart. Record unavailable adapters as unsupported.

## Task 8: Replace local console apply with transactional desired state

**Modify:** `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`,
`input/connectivity.py`, `type/connectivity.py`, `auth/require.py`;
`09_uns_model/src/uns_model/connectivity.py`, `tables.py`.
**Create:** `07_uns_graphql/src/uns_graphql/mutations/edge.py`, `queries/edge.py`,
`type/edge.py`; `07_uns_graphql/test/mutations/test_edge_configuration.py`.
**Modify:** existing connectivity mutation tests and GraphQL app schema composition.

- [ ] Add explicit `edge_id`, optimistic `expected_revision`, and Modbus protocol
  configuration to cloud-mode writes. Separate public responses from secret inputs.
- [ ] Write a regression test whose XML writer, Edge HTTP client, and PLC client
  raise if called. A cloud-mode save while the edge is offline must still commit
  the catalog/snapshot and return `pending`, not `connected` or `applied`.
- [ ] Run `uv run --package uns_graphql pytest 07_uns_graphql/test/mutations/test_edge_configuration.py -n 0 -v`.
- [ ] Replace `_sync_edge`/`_finish_live_apply` in cloud mode with the repository
  transaction in Task 4. Preserve explicit local-development mode during migration;
  no cloud failure may fall back to local XML or direct network calls.
- [ ] Add admin enrollment/revocation/edge assignment and scoped engineer grants.
  Saving/deleting tags/servers creates only the assigned edge's next snapshot.
  Changing edge assignment requires an explicit fenced migration, not two active
  collectors on the same source.
- [ ] Make `desired`, `applied`, `connection_health`, and `last_seen` distinct fields.
  Replace secret-bearing fields with presence indicators. Reject writes for protocol
  capabilities the target edge has not advertised/qualified.
- [ ] Run the new suite and `uv run --package uns_graphql pytest 07_uns_graphql/test/mutations/test_connectivity.py -n 0 -v`.

## Task 9: Outbound management jobs for discovery and connection tests

**Create:** `07_uns_graphql/src/uns_graphql/edge_api/jobs.py`, agent `jobs.py`;
`07_uns_graphql/test/edge_api/test_jobs.py`, `15_uns_edge_agent/test/test_jobs.py`.
**Modify:** GraphQL connectivity queries/mutations/subscriptions and Edge API router.

- [ ] Define jobs with `job_id`, `edge_id`, `connection_id`, `config_revision`,
  `kind` (`test_connection` or `browse_tags`), `cursor`, `expires_at`, and lease.
  Add `GET /api/edge/v1/jobs` and `POST /api/edge/v1/jobs/{job_id}/result`.
- [ ] Test wrong-edge jobs, revision mismatch, duplicate results, expired jobs,
  a disconnected edge, and unsupported discovery capability. Bound jobs to one
  concurrent operation, 60-second execution, five-minute expiry, 500 tags/page,
  1 MiB response, 100 pending jobs per edge, and 24-hour result retention.
- [ ] Run `uv run --package uns_graphql pytest 07_uns_graphql/test/edge_api/test_jobs.py -n 0 -v`
  and `uv run --package uns_edge_agent pytest 15_uns_edge_agent/test/test_jobs.py -n 0 -v` independently.
- [ ] Implement jobs through the local Edge API only. Persist/correlate results;
  no arbitrary target URL, shell, protocol write, or continuous raw value stream.
- [ ] Change cloud-mode browse/test actions to return a job ID/status. Replace
  recursive synchronous discovery with paged results. Cloud live-node reads and
  direct OPC subscriptions are unavailable; route live console values through the
  existing central streams. Keep manual tag entry when discovery is unsupported.
- [ ] Rerun both suites and existing connectivity query/subscription tests. Prove
  cloud profile never opens OPC UA, Modbus, S7, or EtherNet/IP sockets.

## Task 10: Secure central MQTT and route activation barrier

**Create:** `deploy/cloud/broker/README.md`, `deploy/cloud/broker/config.xml`,
`deploy/cloud/broker/authorization/` versioned qualified-extension configuration;
`00_uns_config/src/uns_config/route_release.py`,
`00_uns_config/test/test_route_release.py`, `deploy/test/test_mqtt_boundary.py`;
`07_uns_graphql/src/uns_graphql/edge_api/route_release.py`,
`07_uns_graphql/test/edge_api/test_route_release.py`.
**Modify:** `06_uns_kafka/src/uns_kafka/uns_kafka_config.py`,
`uns_kafka_listener.py`, health/metrics; `02_mqtt-cluster` TLS settings if necessary.

- [ ] Using the Task 1 qualified broker profile, configure TLS 1.2/1.3, required
  client certificates, per-principal authorization, bounded queues, persistence,
  and documented session parameters. Implement the selected extension's supported
  ACL/certificate activation/revocation path; refuse startup with missing authorization.
- [ ] Add real-broker tests: edge A can publish its registered filters; cannot
  publish B's, subscribe, or access management topics; an anonymous/expired/revoked
  certificate is refused. An active revoked client must stop publishing within the
  measured revocation bound, not only after its next reconnect.
- [ ] Run `uv run pytest deploy/test/test_mqtt_boundary.py -n 0 -v`.
- [ ] Define `RouteRelease(revision, digest, publication_routes, principal_grants)`
  and active-status records for broker authorization and mapper subscriptions.
  Persist pending route releases; validate symbolically with existing route code.
  The runtime owner activates the complete immutable route/subscription snapshot
  and reports its revision; existing in-flight events keep frozen metadata.
- [ ] Add `uns_route_release_worker` as a cloud-only entrypoint owning activation
  under a SQL lease. It uses the qualified broker extension's administration API
  and a private authenticated mapper configuration endpoint. Define that endpoint
  in `06_uns_kafka/src/uns_kafka/route_control.py`; enqueue changes to the ingestion
  owner rather than modifying active routes from an HTTP thread. Its credentials
  authorize route administration only. Test worker failover and stale activation
  responses in `07_uns_graphql/test/edge_api/test_route_release.py` and
  `06_uns_kafka/test/test_route_control.py`.
- [ ] Implement the barrier:

```text
stage routes -> validate overlap/identity -> activate mapper route+subscriptions
            -> activate broker grants -> verify both revisions
            -> release dependent desired configuration to edge
```

In-flight old topics remain recognized during a bounded drain; removal is explicit.
An unavailable broker/mapper leaves configuration `waiting_for_routes`, with old
collection still active. Startup config uses the last verified release. No service
gets Docker-socket privileges to update configuration.

- [ ] Add tests for half-activated release, bad digest, overlapping filters, late
  activation reports, and resumed activation after restart. Run
  `uv run --package uns_config pytest 00_uns_config/test/test_route_release.py -n 0 -v`.
- [ ] Test fresh retained publications versus retained bootstrap across the actual
  two-broker bridge. Disable retained bootstrap into historical flow without losing
  fresh retained traffic; preserve payload bytes. Record protocol-specific lifecycle
  limitations such as disabled cloud-triggered Sparkplug rebirth.
- [ ] Verify MQTT acknowledgement still follows canonical Kafka confirmation in
  ingestion. Run the existing publication-ingest regression suite. Report upstream
  broker acknowledgement/disk-persistence limitations separately.

## Task 11: Reproducible DMZ installation bundle

**Create:** `deploy/edge/compose.yml`, `hivemq/config.xml.template`,
`agent.yaml.example`, `install.sh`, `verify.sh`, `upgrade.sh`, `release.json`;
`docs/operations/dmz-edge-installation.md`; `deploy/test/test_edge_package.py`.

- [ ] Write manifest tests for exactly two long-running services in the **base**
  deployment (Task 11A adds optional simulator services), digest-pinned
  images, automatic restart, private authenticated Edge API, no host API port,
  no agent listening port, no privileged mode/Docker socket, durable configuration,
  durable licensed bridge data, agent journal/keys, and no default credentials.
- [ ] Run `uv run pytest deploy/test/test_edge_package.py -n 0 -v`.
- [ ] Implement the artifact layout and installation utilities. `install.sh` checks
  supported Linux/runtime, permissions, disk, trusted release digest, and existing
  state; rerunning preserves identity/configuration. Never download/execute an
  unverified script. `upgrade.sh` requires a named release and preserves backups.
- [ ] Provide these **future Linux VM commands**, from an extracted verified bundle:

```bash
sudo ./install.sh --destination /opt/uns-edge
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml up -d
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml exec uns-edge-agent uns_edge_enroll
sudo ./verify.sh --destination /opt/uns-edge
```

Enrollment prompts for the single-use token without echo. Destination API names and
trust roots are installed from the administrator-supplied config, not typed into
unchecked download commands. Explain registry access versus `docker load` of a
verified image archive, and the separate OT firewall permission requirement.

- [ ] Configure outbound bridge forwarding only, no remote subscriptions, stable
  client ID, mTLS keystore, verified hostname, persistent session, finite licensed
  buffer, and explicit retain rules proven in Task 10.
- [ ] Test local configuration persistence through Edge restart and API-managed
  writes. Edge owns its writable config; the agent has access only to necessary
  credential/journal locations and local API, not arbitrary host files.
- [ ] Run the package tests and, with generated fixture secrets,
  `docker compose -f deploy/edge/compose.yml config --quiet`.
  Qualification also requires a disposable Linux VM boot/install/reboot, not only
  Compose syntax validation. Record both evidence types separately.

## Task 11A: Edge-VM simulation profile and hardware-free commissioning

**Dependencies:** Tasks 2 and 7 provide the test topology/protocol adapter contracts;
Task 11 provides the installable bundle. Full console acceptance also requires
Tasks 12 and 14. Keep existing task numbers to preserve earlier references.

**Modify:** `HiveMQ-Simulator.sh`, `conf/simulator/Dockerfile`,
`conf/simulator/multi_system_publishers.py`, `Dockerfile.multi-system`,
`00_uns_config/test/test_multi_system_simulator.py`, `deploy/edge/release.json`,
installation/upgrade utilities and bundle tests.
**Create:** `deploy/edge/compose.simulation.yml`,
`deploy/edge/simulation/connections.json`, `publication-routes.yaml`, `README.md`;
`conf/simulator/protocols/pyproject.toml`, `Dockerfile`, `opcua_server.py`,
`modbus_server.py`, `fixtures.json`;
`conf/simulator/test/test_edge_publishers.py`, `test_protocol_servers.py`;
`deploy/test/test_edge_simulation.py`, `test_simulated_config_roundtrip.py`;
`docs/operations/edge-simulation-demo.md`.

- [ ] Define overlay profile `edge-sim` with four named services: `oee-simulator`,
  `multi-system-simulator`, `opcua-simulator`, and `modbus-simulator`. Reuse the two
  existing MQTT scripts/image recipes; add only transport/identity/test-mode options
  they need. Pin release digests rather than building from source on the VM.
- [ ] Write overlay tests proving the base still runs only Edge/agent; enabling
  the overlay adds four sources, private `sim-ot` networking, no host-published
  simulator ports, no cloud credentials/egress, and no direct cloud broker address.
  All MQTT publishers resolve their destination to local `hivemq-edge:8883`.
- [ ] Run `uv run pytest deploy/test/test_edge_simulation.py -n 0 -v` before
  implementing the overlay; expect missing profile/network behavior.
- [ ] Extend existing `H`/`P` and `MQTT_HOST`/`MQTT_PORT` configuration for scoped
  local MQTT/TLS credentials and hostname verification. Use secret files, not
  command strings containing passwords. Keep host-side development behavior intact.
  Use per-edge client IDs (the shell currently uses fixed `mqtt_oee_demo`) and
  fresh boot identity or persisted sequences (the Python publisher currently resets
  sequence under a fixed default boot ID). Wait for successful MQTT acknowledgements
  before labelling generated cases broker-accepted; distinguish admission from ACK.
- [ ] Add a bounded deterministic acceptance mode with run ID/seed, finite cases,
  expected values and an output manifest. Preserve the existing randomized OEE
  demonstration. Disable intentionally malformed payloads for the happy-path run;
  run them separately with expected rejection counts/reasons. Scope prefixes to a
  dedicated simulation namespace, preserving current application suffixes and
  matching route/ACL registrations. No new canonical-envelope field is required.
- [ ] Write behavioral tests for TLS verification failure, denied topic, rejected
  PUBACK, restart identity, bounded completion, and reproducible accepted payloads.
  Run `uv run pytest conf/simulator/test/test_edge_publishers.py 00_uns_config/test/test_multi_system_simulator.py -n 0 -v`.
- [ ] Implement the protocol servers as standalone test sources with locked
  dependencies and version-qualified APIs. Reuse existing protocol fixtures where
  possible. They expose protocol services, not MQTT publishers or a second collector:

```text
OPC UA: opc.tcp://opcua-simulator:4840/uns-sim/
  namespace URI: urn:uns:edge-simulation (resolve index when browsing)
  string node IDs: Temperature, Pressure, SampleCounter
Modbus TCP: modbus-simulator:1502
  unit ID 1, zero-based holding registers:
  0 = temperature * 10; 1 = pressure * 100; 2 = sample counter
  unsigned 16-bit values; explicitly document address convention and scaling
```

The finite fixture uses known held values long enough for configured polling to
observe them. Publish the schedule in `fixtures.json`; do not assume every generated
value is sampled. Application register writes are rejected; changing fixture values
is a local test-runner action, never a cloud process-control command.

- [ ] Run `uv run pytest conf/simulator/test/test_protocol_servers.py -n 0 -v` using
  actual protocol clients against the fixture servers. Verify readable nodes/registers,
  stable namespace/address semantics, and bounded fixture behavior. No PLC hardware
  is required. Include these dependencies explicitly in the isolated test environment.
- [ ] Configure `sim-ot` as internal-only. Edge joins it and the outbound network;
  the agent does not join `sim-ot`. Allow only the fixture endpoints in simulation
  bootstrap policy and provision appropriate certificates/trust. Test both destination
  refusal and successful local collection. Simulator images have no Docker socket.
- [ ] Include the overlay, fixture manifest, sample connection inputs, simulation
  route registrations, and all four images in online/offline release bundles. Sample
  connection inputs must be submitted through cloud mutations after enrollment;
  starting the overlay does not install adapters locally or pre-report an apply.
- [ ] Document these **future Linux VM commands**, after Task 11 enrollment:

```bash
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml -f /opt/uns-edge/compose.simulation.yml --profile edge-sim up -d
sudo ./verify.sh --destination /opt/uns-edge --profile edge-sim
```

`install.sh` copies simulation artifacts but enables none by default. The extended
`verify.sh` checks six service health states, local-only destinations, cloud enrollment,
and route readiness; end-to-end success additionally requires the cloud actions below.

- [ ] Implement `test_simulated_config_roundtrip.py` using the actual cloud API,
  authenticated edge poll/apply loop, and real protocol servers. Extend `cloud_edge`
  from Task 2 with `configure_simulated_source(protocol)` returning a revision,
  `change_simulated_mapping(protocol)` returning a newer revision, and
  `wait_source_data(protocol, revision, timeout)` returning local MQTT capture,
  canonical records, and physical lake rows. Test both `opcua` and `modbus`:

```python
import pytest

@pytest.mark.parametrize("protocol", ["opcua", "modbus"])
def test_cloud_configuration_changes_simulated_collection(cloud_edge, protocol):
    revision = cloud_edge.configure_simulated_source(protocol)
    report = cloud_edge.wait_applied("edge-01", revision, timeout=120)
    assert report.applied_revision == revision
    first = cloud_edge.wait_source_data(protocol, revision, timeout=120)
    assert first.values_match_fixture
    assert first.lake_payloads_match_local_mqtt
    changed = cloud_edge.change_simulated_mapping(protocol)
    assert changed > revision
    cloud_edge.wait_applied("edge-01", changed, timeout=120)
    next_data = cloud_edge.wait_source_data(protocol, changed, timeout=120)
    assert next_data.uses_updated_mapping
```

These evidence fields must derive from observed records, not the submitted desired
configuration. The fixture maps revisions to apply timestamps/topic selections in
its manifest; do not pretend telemetry already carries an edge configuration revision.
For protocol data, compare Edge-generated MQTT bytes with lake `original_payload`,
and compare decoded values with the source schedule separately.

- [ ] Run `uv run pytest deploy/test/test_edge_simulation.py deploy/test/test_simulated_config_roundtrip.py -n 0 -v`
  and validate the merged Compose files with fixture secrets. Verify MQTT generators
  still flow if protocol adapters are absent, while protocol-specific topics start
  only after the cloud configuration applies. Block simulator-to-cloud access to
  prove every simulated publication traverses Edge.
- [ ] Write the operator walkthrough: start/enroll edge-sim, activate routes, observe
  current OEE/MES/LIMS/SAP-shaped data, add OPC UA/Modbus from the cloud console,
  observe applied status and values, change mappings, interrupt HTTPS only/save a
  pending revision/reconnect, then separately interrupt MQTT/reconnect. Exclude
  retained bootstrap and bounded pre-change backlog when checking stopped mappings.
- [ ] Run that walkthrough on the actual edge VM and chosen cloud host; record
  host/provider, run ID, revisions, source values, local/cloud timestamps, Kafka
  coordinates, lake paths and byte comparisons, firewall evidence, and screenshots
  of live values/applied status. CI simulation is not evidence of a completed
  VM-to-cloud deployment. No physical PLC is a prerequisite for this milestone.
- [ ] Document stopping/removing only the four simulator services, preserving
  Edge/agent volumes and identity, then explicitly removing simulation adapters and
  disabling their routes through normal configuration. Never use `down -v` to leave
  simulation mode. Preserve test history; real-source cutover uses new registrations.
- [ ] Document adding a real PLC alongside the running simulators: approve its
  destination at the OT firewall/local allowlist, enter its actual protocol/security/
  node or register settings in the cloud console, activate distinct routes, and
  observe its own applied/connection status. This must require no application-code
  change, reinstall, re-enrollment, or global switch that redirects other connections.

**Exit:** The same installable edge release can show current simulated on-premises
data flowing to the real cloud and cloud-authored OPC UA/Modbus configuration taking
effect locally. Basic connected demonstration and licensed outage durability are
reported separately; the former does not establish the latter.

## Task 12: Production cloud bundle and provider runbooks

**Create:** `deploy/cloud/compose.yml`, `settings.yaml.example`,
`proxy/nginx.conf`, `release.json`, `validate.py`, `hostinger.md`, `aws-ec2.md`;
`docs/operations/cloud-platform.md`; `deploy/test/test_cloud_package.py`.
**Modify:** owned Dockerfiles, `00_uns_config/src/uns_config/platform.py`, loader
configuration, and frontend reverse-proxy configuration where runtime URLs require it.

- [ ] Write manifest tests forbidding HiveMQ Edge, PLC collectors, simulator
  services, `start-dev`, floating images, broad config mounts, default credentials,
  localhost public URLs, public Kafka/SQL/Neo4j/metrics ports, and public API bypass.
  Simulators belong exclusively to Task 11A's optional **edge** overlay; cloud
  simulation routes are permitted without cloud-local source generators.
- [ ] Run `uv run pytest deploy/test/test_cloud_package.py -n 0 -v`.
- [ ] Implement a dedicated production bundle with compatible existing service
  entrypoints, one-shot database/topic initialization, production OIDC with durable
  SQL, and HTTPS/WSS console/API/Grafana routing. Enrollment and mTLS management use
  separate server blocks. MQTT TLS terminates at the qualified broker, not an HTTP
  proxy pretending to support MQTT. Explicitly restrict proxy trust headers.
- [ ] Implement runtime URL settings and one public OIDC issuer; internal discovery
  transport does not change issuer identity. Health/readiness checks and retry
  behavior must work after dependency restarts, not just Compose startup ordering.
- [ ] Inventory remaining writable state: hierarchy/config edits, model migrations,
  Grafana state, Keycloak database, Neo4j, Kafka, Timescale, CA/secret keys. Preserve
  single-owner writers and document replica ceilings. Kafka consumers can scale only
  after partition ownership/client-ID behavior is qualified; no blanket autoscaling.
- [ ] Implement explicit resource/queue limits, log rotation, off-host encrypted
  backup jobs, and target object-store credentials. Separate release metadata from
  secrets; no full repository or development `.secrets.yaml` mount in production.
- [ ] Write Hostinger VPS and AWS EC2 procedures for Linux provisioning, disk,
  public DNS, firewall/security group, TLS, container installation, release upload,
  credential injection, start, verification, backup, and rollback. Both use the
  same images/contracts; provider account operations remain human prerequisites.
- [ ] Test validation errors for missing CA/key material, unqualified broker release,
  insufficient declared disk/retention budget, HTTP public origin, or incompatible
  envelope/config versions. Run cloud-package tests and fixture-configured
  `docker compose -f deploy/cloud/compose.yml config --quiet`.
- [ ] Record the single-server failure domain. Do not call the EC2 profile HA or
  substitute RDS/MSK/IoT products without separate compatibility qualification.

## Task 13: Generic business HTTPS push with durable outbox

**Create:** `09_uns_model/src/uns_model/publication_outbox.py`,
`09_uns_model/migrations/versions/0011_publication_outbox.py`,
`09_uns_model/test/test_publication_outbox.py`;
`07_uns_graphql/src/uns_graphql/publication_api/{__init__,router,service,worker}.py`,
`07_uns_graphql/test/publication_api/test_ingress.py`, `test_worker.py`;
`docs/operations/business-publisher-onboarding.md`.
**Modify:** GraphQL app router wiring/package scripts, cloud bundle, route registration.

- [ ] Define `POST /api/publications/v1/routes/{route_id}` and
  `GET /api/publications/v1/receipts/{receipt_id}` for scoped business machine
  identities. Required `Idempotency-Key`; optional validated occurrence-time header;
  body is raw bytes. Route registration supplies MQTT destination/app/site/schema/
  content type; reject conflicting headers, unregistered routes, or forged identity.
- [ ] Define `Outbox.admit(principal, route, key, body, metadata) -> Receipt`,
  `lease_batch(worker_id, limit)`, `confirm_broker(receipt_id, lease)`, and
  `retry(receipt_id, lease, error_code)`. SQL uniqueness scopes the key to principal
  and route; content digest includes raw bytes and immutable metadata.
- [ ] Write tests: bytes including whitespace/binary/empty remain exact; concurrent
  duplicate keys yield one receipt; content conflict is 409; full encoded envelope
  size over 1 MiB is 413; database failure/capacity exhaustion returns 503 and no 202.

```text
POST key=order-42, body=A -> commit outbox -> 202 receipt=R
POST key=order-42, body=A -> same R (within seven-day terminal retention)
POST key=order-42, body=B -> 409
worker publish succeeds, dies before SQL update -> lease expires -> same wrapper retry
MQTT callback error/timeout -> receipt not broker_accepted
```

- [ ] Run `uv run --package uns_model pytest 09_uns_model/test/test_publication_outbox.py -n 0 -v`
  and `uv run --package uns_graphql pytest 07_uns_graphql/test/publication_api -n 0 -v` independently.
- [ ] Implement transactional admission and global/per-principal byte budgets, with
  locked reservation rows to avoid concurrent over-admission. Default queue budget
  is 1 GiB and per-principal 128 MiB, configurable; reserve space for receipt metadata
  and terminal records too. Do not drop unresolved rows to reclaim space.
- [ ] Persist the explicit `uns-publication-v1` wrapper once. Use receipt UUID as
  `source_boot_id`, sequence 0, and frozen registered metadata. Register its MQTT
  destination as wrapper mode. Admission checks the same complete-envelope size
  logic as canonical ingestion, including base64 and metadata overhead.
- [ ] Implement `uns_publication_outbox_worker` with at most 100 leased records and
  8 MiB active bytes, 60-second renewable leases, bounded exponential retry, and
  manual recovery after terminal configuration/auth failures. Confirm only an
  actual successful QoS 1 callback/PUBACK; retain identical bytes after ambiguity.
- [ ] Document 202/outbox versus broker acceptance versus Kafka/lake delivery, the
  seven-day terminal idempotency window, polling receipt authorization, source
  retry behavior, and that no reverse business writeback is performed.
- [ ] Rerun suites and qualify machine/SAP-shaped/MES-shaped/LIMS-shaped bodies
  through both direct MQTT and HTTP routes. Record simulations as contract evidence,
  not connections to live vendor products.

## Task 14: Edge-aware connectivity console

**Modify:** `11_frontend/src/components/connectivity/ConnectivityView.tsx`,
`BrowseDataDrawer.tsx`, `SignalsTab.tsx`, existing tests;
`11_frontend/src/services/graphql/client.ts`, `types.ts`,
`11_frontend/src/lib/connectivity/map-servers.ts`, `validate-server.ts`.
**Create:** `11_frontend/src/components/connectivity/EdgeDevicesPanel.tsx`,
`EdgeDevicesPanel.test.tsx`, `11_frontend/src/lib/connectivity/edge-status.ts`,
`edge-status.test.ts`.

- [ ] Load the repository's applicable UI/layout guidance at implementation time;
  extend existing controls without inventing a new navigation/design system.
- [ ] Write behavior tests for edge selection, admin enrollment, one-time token
  reveal, engineer edge grants, desired/applied revisions, offline/stale state,
  per-adapter failure, Modbus typed settings, unsupported protocol/discovery, and
  asynchronous browse/test results. A save must never imply connection success.
- [ ] Run `npm run test:run -- src/components/connectivity/EdgeDevicesPanel.test.tsx src/lib/connectivity/edge-status.test.ts`
  with working directory `11_frontend`.
- [ ] Implement the panel and edge-aware connection forms. Show statuses
  `waiting_for_routes`, `pending`, `applying`, `applied`, `failed`, `degraded`, and
  separate connection/heartbeat state. Expired browse results cannot overwrite
  newly edited tags or topics. Secrets remain write-only and are cleared from forms
  after submission; enrollment tokens never go to persistent browser storage.
- [ ] Preserve edited topic mappings and explicit subscriptions when importing
  discovered tags. Existing live data uses central subscriptions; no browser
  connection to a DMZ address or HiveMQ Edge console.
- [ ] Exercise the Task 11A walkthrough with the cloud console: show edge enrollment,
  pending/applied revision, both simulated industrial connections, central live values,
  and a subsequent mapping change. Identify the simulation site clearly using its
  registered name; never imply the fixtures are real PLC or vendor connections.
- [ ] Run `npm run test:run -- src/components/connectivity src/lib/connectivity`
  then `npm run lint`, each with working directory `11_frontend`.

## Task 15: Release pipeline, failure qualification, and restore

**Create:** `.github/workflows/cloud-edge-release.yml`,
`deploy/test/test_configuration_recovery.py`, `test_business_delivery.py`,
`test_restore.py`. Complete `docs/benchmarks/cloud-edge-qualification.md`.
**Modify:** `08_uns_observability/prometheus/alerts.yml` and relevant dashboards.

- [ ] Build/test OCI images with explicit dependency locks and architecture matrix;
  publish release manifests/checksums and verified online/offline bundles. Never
  embed credentials/licenses in an image. Publish only through an explicitly
  authorized release job, not on every local test invocation.
  Include the optional edge-sim overlay and four simulator images; verify base and
  simulation manifests separately and share fixture image digests with CI.
- [ ] Execute the following matrix on the isolated topology:

| Fault | Assertion |
| --- | --- |
| All simulators disabled | Base services and real-device configuration workflows remain functional; no dependency on fixture services or generated values. |
| Real-shaped endpoint and simulator configured together | Both use identical released adapter code, with separate endpoint settings, identities, topics, and status. |
| No PLC hardware, edge-sim enabled | Current MQTT generators plus protocol test servers demonstrate VM-to-cloud data and cloud-to-edge configuration; no cloud-local data shortcut. |
| Cloud mapping changed on a simulated source | Applied revision/readback and new values/topics agree; old retained or queued data is not mistaken for new sampling. |
| HTTPS-only outage during simulation | Configuration stays pending while MQTT continues, then applies after HTTPS recovery. |
| Cloud management unavailable | Current Edge adapters keep running; pending configuration eventually reconciles. |
| VM power loss during apply | Journal survives; readback determines actual state; no false applied report. |
| Cloud/database restart after snapshot commit | Pending desired state is still retrievable. |
| HTTPS response loss after enrollment/report | Same identity/report outcome; no duplicate enrollment or state regression. |
| Duplicate/cloned agent | Lease fences remote effects; installer prevents accidental identity cloning; cloned VM requires new enrollment. |
| Bridge WAN outage plus Edge restart | Licensed buffer survives; reconcile physical event IDs/coordinates and duplicates. |
| Cloud MQTT crash immediately after PUBACK | Measure pre-Kafka loss window and compare with accepted RPO. |
| Kafka/mapper downtime and full broker queue | Bound pressure, expose drops/rejections, and report unsupported outage duration. |
| Store/historian outage | Existing independent-consumer and upload-before-commit guarantees remain. |
| Partial route/ACL release | New edge configuration is withheld; old route remains usable. |
| Certificate expiry/revocation/rotation | No TLS downgrade; active session revocation tested, not just reconnect refusal. |
| Outbox publish-before-status crash | Same wrapper/source identity is retried; duplicate physical deliveries expected. |
| HTTP flood or oversized configuration | Explicit bounded refusal; no unbounded memory/disk growth. |
| Two sites with identical local names | Scoped state/ACLs prevent collisions and cross-edge deletion. |
| Unsupported discovery or southbound mapping | Clear unsupported/rejected state; no fallback cloud-to-OT call. |

- [ ] Run `uv run pytest deploy/test -n 0 -v` against the isolated fixture only.
  Run focused module regressions from Tasks 3–14 after relevant changes; report
  skipped integration cases separately from passing unit tests.
- [ ] Measure live/catch-up bytes/sec, RSS, edge buffer usable bytes, broker queue
  headroom, Kafka retention, outbox disk use, configuration latency, restart recovery,
  certificate renewal/revocation bounds, and object verification bandwidth.
- [ ] Restore SQL/catalog, encrypted secrets with keys, identity database, broker
  state, and required data/log state into a separate deployment. Verify pending
  snapshots/outbox receipts, preserved identities, and meaningful Kafka positions.
  Restore tests must not silently reset offsets or discard unarchived records.
- [ ] Document status per profile: Linux fixture, clean DMZ VM, Hostinger VPS, AWS
  EC2, actual broker edition, and object backend. A Linux fixture passing does not
  mean either cloud provider was deployed. Record measured RPO/RTO, not invented SLOs.
  Separately record `edge-sim on VM -> actual cloud` acceptance, then physical PLC/
  SCADA acceptance when hardware is available. Do not block the simulation milestone
  on unavailable hardware or count it as hardware/vendor qualification.

## Task 16: Canary migration, runbooks, and completion review

**Complete:** the cloud, DMZ installation, business onboarding, and edge-simulation
operations runbooks, release manifests, package READMEs,
qualification report. Update `README.md` with the cloud/edge deployment entrypoint.

- [ ] Write the operator sequence with named ownership:

```text
Cloud IT: provision server/DNS/secrets/license/backups -> install qualified release
Platform admin: verify readers/routes -> register one canary edge -> issue token
Site IT: allow DMZ egress and OT destinations -> install/enroll DMZ release
Platform admin: assign canary connections -> activate routes/ACLs -> publish snapshot
Agent: retrieve/apply/verify -> report
Operator: reconcile live data/lake rows -> approve rollout to next edge
```

- [ ] Document fencing the old local collector/bridge, migration of catalog rows,
  stable source identity, and legacy topic handling. Drain/archive the old Kafka
  stream and record its final coordinates; new cluster coordinates are a new
  transport namespace unless a separately qualified migration preserves identity.
  Do not reuse offset numbers as proof of stream continuity.
- [ ] Start the initial canary with Task 11A's edge-sim profile because physical
  PLCs are unavailable. Complete the real VM/cloud walkthrough before scheduling
  real-source migration; document changing from simulation to real connection
  registrations without reinstalling or re-enrolling the edge.
- [ ] Keep old compatible readers/data until the rollout/retention window ends.
  Rollback uses a new desired revision or compatible pinned software; no automatic
  destructive migration downgrade. Edge reboot does not trigger re-enrollment.
- [ ] Document IT recovery for lost VM, stolen identity, long-offline expired cert,
  failed upgrade, full disk, DNS/CA change, partial apply, and unavailable vendor
  source. Mark what requires a local administrator versus cloud-console action.
- [ ] Check every design acceptance row against an executed test or explicitly
  blocked qualification. Review diffs for credential leaks, mixed user work,
  network assumptions, managed-adapter ownership, and unsafe success assertions.
- [ ] Run `git diff --check` and `graphify update .`. Report code graph refresh
  separately from semantic indexing of these Markdown documents.
- [ ] Handoff the release/artifact locations, exact commands actually verified,
  supported protocols, license/hosting prerequisites, observed loss/duplicate
  boundaries, provider qualification status, and remaining source-specific
  integration work. Commit only on explicit request.

## Coverage and completion definition

| Design requirement | Tasks |
| --- | --- |
| Hosting, approved boundaries, baseline | 1, 2, 10–12 |
| VM installation and outbound firewall | 2, 6, 11, 16 |
| Edge simulation and hardware-free data/configuration round trip | 2, 7, 11A, 14–16 |
| Enrollment, scopes, secrets, rotation | 4–6, 10, 14–15 |
| Desired/reported state and partial apply | 3–8, 14–15 |
| OPC UA/Modbus and discovery | 7–9, 14–15 |
| Registered secure MQTT and delivery limits | 1, 10–12, 15–16 |
| Business push boundaries | 10, 13, 15 |
| Operational readiness, restore, migration | 12, 15–16 |

Implementation is complete when the installable cloud and DMZ bundles demonstrate
outbound-only operation; an owner can configure OPC UA and Modbus remotely with
truthful applied/health status; authorized machine and generic business publications
reach the existing raw lake contract; and failure/restore evidence establishes the
supported operating envelope. Real-device-ready adapters and configurable endpoints
are mandatory; simulator-only behavior is not completion. The initial hardware-free milestone must run the
current MQTT simulators and protocol test servers on the edge VM and prove both
data forwarding to the actual cloud and configuration changes back through the
outbound agent channel. Physical PLC/vendor qualification is recorded separately:
hardware unavailability may block evidence for a particular device, but does not
remove implementation of real-device connectivity from scope.
Production rollout remains a distinct authorized
operator action. Native vendor connectors and an HA tier are not silently included
in that completion claim.
