# Cloud Platform and Outbound DMZ Edge — Qualification Report

> **Status:** Baseline frozen at programme Task 1. Product and infrastructure
> qualification are **not complete**. Items that require operator licenses, pinned
> production images, or live broker/edge infrastructure are recorded as **blocked**.
> Do not treat this document as production qualification evidence.

Design reference: [Cloud-hosted UNS with outbound-only DMZ management](../superpowers/specs/2026-09-12-cloud-platform-outbound-edge-design.md).

Implementation plan: [Cloud platform and outbound edge](../superpowers/plans/2026-09-12-cloud-platform-outbound-edge.md).

Related delivery evidence: [UNS-to-lake delivery](./uns-to-lake-delivery.md),
[UNS-to-lake operations](../operations/uns-to-lake-delivery.md).

Deployment validator input: [`deploy/release-contract.json`](../../deploy/release-contract.json).

## 1. Run metadata

| Field | Value |
| --- | --- |
| Date (UTC) | 2026-09-12 |
| Operator | Task 1 agent (automated baseline capture) |
| Git branch | `feat/cloud-platform-outbound-edge` |
| Git commit (baseline) | `5c862964` (`chore(graph): update community labels and graph report metrics`) |
| Working tree at start | Clean — no staged or unstaged changes |
| Programme base commit | `5c862964` (per plan) |
| Qualification profile | `isolated-qualification` only until `release-contract.json` status is `qualified` |

### 1.1 Starting git baseline (independent commands)

```text
git status --short          → (empty)
git diff --stat             → (empty)
git diff --cached --stat    → (empty)
git log --oneline -10       → 5c862964 chore(graph): update community labels...
                            f3349763 feat(events): enhance event schema...
                            130f6f30 refactor(connectivity): improve table layout...
                            092488b8 test(connectivity): add test for long lastError...
                            e2196ae2 fix(docker-compose): extend start periods...
                            9f5eea02 fix(kafka): correct environment variable naming...
                            18a6b094 refactor(oee_mqtt_simulator): update Docker...
                            1ed6b07e feat(docker): enhance docker-compose...
                            827c9f69 feat(datalake): update historic event lake mapper...
                            6e995892 fix(tests): ensure proper database closure...
```

No pre-existing staged delivery/UI work was present in the working tree at Task 1 start.

## 2. Repository baseline (development stack)

Observations from the inspected working tree at `5c862964`. These describe current
development behaviour, not a qualified production deployment.

| Location | Current behaviour | Edge-to-cloud production consequence |
| --- | --- | --- |
| `docker-compose.yml` | Development-only; co-locates `hivemq/hivemq-edge:latest` with central Kafka/SQL/GraphQL; publishes MQTT `1883` and Edge console `18080` on the host | **Disabled** in production bundle — Edge runs only on DMZ VM; central stack uses a full HiveMQ broker candidate, not Edge |
| `conf/hivemq/config.xml` | Unencrypted MQTT `1883`, admin HTTP `8080` on `0.0.0.0`, read-only mount; contains `simulation` adapter plus catalog-owned OPC UA fixtures from local dev | **Disabled** for cloud console writes — agent applies via private Edge API; production uses TLS/mTLS and writable persistent config volume |
| `00_uns_config/.../hivemq_edge_api.py` | Synchronous Edge Management API v1 (`/api/v1/...`); OPC UA, S7, EtherNet/IP; deletes catalog adapters absent from supplied list; **no Modbus** | Retained on edge agent path; **disabled** from cloud GraphQL process |
| `00_uns_config/.../hivemq_edge_xml.py` | Renders/edits local `config.xml` | **Disabled** from cloud — configuration is desired-state over HTTPS only |
| `07_uns_graphql/.../mutations/connectivity.py` | `after_flush` writes XML then `apply_catalog_adapters_live` | **Disabled** in edge-to-cloud profile — agent reconciles |
| `07_uns_graphql/.../queries/connectivity.py` | Direct OPC UA browse/test/read via `uns_opcua` from GraphQL | **Disabled** — replaced by bounded agent management jobs (not yet implemented) |
| `09_uns_model/.../connectivity.py` | Shared catalog; no per-edge desired/reported lifecycle | Gap — Tasks 3–9 |
| `00_uns_config/.../platform.py` | Public URLs default to `http://localhost` | Must be replaced in production bundle |
| `10_uns_opcua` | Separate local collector (`legacy-opcua` profile) | **Disabled** in production — must not duplicate Edge collection |
| `HiveMQ-Simulator.sh`, `conf/simulator/*` | MQTT publishers; `H`/`P` select broker (default `localhost:1883`; stack uses `uns_mqtt_broker`) | Edge-sim profile must target `hivemq-edge:8883` only; **never** cloud broker |
| `conf/settings.yaml` `hivemq_edge.base_url` | `http://127.0.0.1:18080` | Local dev only; agent uses `https://hivemq-edge:8443` on private network |

### 2.1 Graphify orientation (`graphify query "hivemq_edge_api connectivity OPC UA deployment" --budget 2000`)

Traversal: BFS depth 2 from `connectivity()` and `hivemq_edge_api.py`; 129 nodes (67 truncated by budget).

Confirmed high-signal paths:

| Category | Source paths |
| --- | --- |
| Edge API client | `00_uns_config/src/uns_config/hivemq_edge_api.py` |
| XML config writer | `00_uns_config/src/uns_config/hivemq_edge_xml.py` |
| GraphQL writes | `07_uns_graphql/src/uns_graphql/mutations/connectivity.py` |
| GraphQL OPC probes | `07_uns_graphql/src/uns_graphql/queries/connectivity.py`, `10_uns_opcua/src/uns_opcua/session.py` |
| Shared catalog | `09_uns_model/src/uns_model/connectivity.py`, `tables.py` |
| Tests | `00_uns_config/test/test_hivemq_edge_api.py`, `test_hivemq_edge_xml.py`, `07_uns_graphql/test/mutations/test_connectivity.py` |

### 2.2 Direct PLC / protocol calls (current code)

| Call site | Protocol / target | Edge-to-cloud profile |
| --- | --- | --- |
| `mutations/connectivity.py` → `open_client` / `opcua_browse` | OPC UA discovery on configured endpoint | **Disabled** from cloud GraphQL |
| `queries/connectivity.py` → `test_opc_ua_connection`, `browse_opc_ua`, `discover_opc_ua_variables`, `read_opc_ua_nodes` | OPC UA anonymous sessions from GraphQL host | **Disabled** from cloud GraphQL |
| `hivemq_edge_api.py` → Edge adapter CRUD | HiveMQ Edge Management API (not wire-level PLC) | **Moved** to edge agent private calls only |
| `10_uns_opcua` collector | OPC UA poll + MQTT publish (`legacy-opcua` profile) | **Disabled** in production |

S7 and EtherNet/IP have no cloud-side wire probes; tags are authored manually in the console and applied through Edge adapters only.

### 2.3 Configuration writers (current code)

| Writer | Mechanism | Edge-to-cloud profile |
| --- | --- | --- |
| `apply_catalog_adapters_file` | Rewrites `conf/hivemq/config.xml` | **Disabled** from cloud |
| `apply_catalog_adapters_live` | Edge REST API from GraphQL after flush | **Disabled** from cloud |
| Future agent apply | Private HTTPS poll → local Edge API | **Enabled** (Tasks 7–9) |

### 2.4 MQTT command and Sparkplug rebirth publishers

| Component | Role | Edge-to-cloud profile |
| --- | --- | --- |
| `spb_mapper_client` (`05_sparkplugb`) | Subscribes to `spBv1.0/...`; handles NCMD/DCMD/NDATA/DDATA; translates to UNS publishes | Remains a **central** consumer; not an edge bridge |
| `HiveMQ-Simulator.sh` | OEE demo MQTT with `-r` retained publishes | Edge-sim only; local `hivemq-edge:8883` |
| `conf/simulator/multi_system_publishers.py` | Halabja machine/MES/LIMS/SAP-shaped MQTT | Edge-sim only; local broker |
| `uns_ingest.classify_event_kind` | Classifies `NCMD`/`DCMD` as `command` | Unchanged classification; cloud bridge denies southbound app topics |
| Edge northbound mappings | QoS 1 telemetry from adapters | **Enabled** edge → cloud only |

No repository component currently publishes Sparkplug NCMD/DCMD rebirth commands to plant equipment. The Sparkplug mapper consumes inbound SCADA traffic in the development stack.

## 3. Canonical reader and lake readiness (delivery plan re-check)

The [multi-system delivery plan](../superpowers/plans/2026-09-11-multi-system-uns-to-lake.md)
header still reads *"Ready for later implementation"*. Task 1 re-measured **actual**
readiness against the codebase at `5c862964`:

| Area | Actual readiness | Evidence |
| --- | --- | --- |
| v2 envelope writer | **Implemented; enabled in shipped config** | `kafka_mapper.ingestion.v2_publications_enabled: true` in `conf/settings.yaml` |
| Historian v1/v2 reader | **Compatible (unit)** | `04_uns_historian/test/test_event_v2_compatibility.py` — 9 passed |
| GraphQL v1/v2 reader | **Compatible (unit)** | `07_uns_graphql/test/backend/test_event_v2_compatibility.py` — 7 passed |
| Lake mapper v1/v2 routing | **Implemented (unit/contract)** | `14_uns_datalake/test` — 143 passed, 6 deselected (`not integrationtest`) |
| Kafka ingest / publication | **Implemented (unit/contract)** | `06_uns_kafka/test` — 72 passed, 20 deselected |
| Config / Edge stack contracts | **Mostly green; one baseline drift** | `00_uns_config/test` — 174 passed, **1 failed** (`test_default_config_has_no_protocol_adapters`: `config.xml` contains `catalog-*` OPC UA adapter from local connectivity saves) |
| Four-domain live acceptance | **Blocked (integration)** | `test_four_domains_reach_lake_with_historian_stopped` exists; requires live MQTT/Kafka/MinIO stack — not executed in Task 1 |
| ADLS live backend | **Not qualified** | Per existing delivery benchmark template |
| AWS S3 production backend | **Not qualified** | Per existing delivery benchmark template |

**Conclusion:** Dual-version readers and lake/kafka contract tests are **code-ready**.
Live multi-system qualification and backend durability rows remain **blocked** or
**not qualified**, matching the existing `uns-to-lake-delivery.md` template state.
The old plan heading overstates production readiness; do not enable production cutover
from Task 1 evidence alone.

### 3.1 Verification commands executed (2026-09-12)

```powershell
# From repository root; module rootdirs avoid conftest import collisions on Windows.
uv run pytest 14_uns_datalake/test --rootdir=14_uns_datalake -c 14_uns_datalake/pyproject.toml -n 0 -m "not integrationtest"
# → 143 passed, 6 deselected

uv run pytest 06_uns_kafka/test --rootdir=06_uns_kafka -c 06_uns_kafka/pyproject.toml -n 0 -m "not integrationtest"
# → 72 passed, 20 deselected

uv run pytest 00_uns_config/test -n 0 -m "not integrationtest"
# → 174 passed, 1 failed (hivemq config catalog adapter drift)

uv run pytest 04_uns_historian/test/test_event_v2_compatibility.py --rootdir=04_uns_historian -c 04_uns_historian/pyproject.toml -n 0
# → 9 passed

uv run pytest 07_uns_graphql/test/backend/test_event_v2_compatibility.py --rootdir=07_uns_graphql -c 07_uns_graphql/pyproject.toml -n 0
# → 7 passed
```

## 4. Product candidates and license gates

**No licenses were purchased and no operator entitlement was supplied during Task 1.**
All digest-pinned production images and commercial features below are **blocked**.

### 4.1 Central full HiveMQ broker (production reference candidate)

| Field | Value | Status |
| --- | --- | --- |
| Role | Cloud UNS MQTT ingress (not HiveMQ Edge) | Candidate selected in design |
| Edition | HiveMQ Enterprise (full broker) | **Blocked** — operator license/edition decision required |
| Image repository (candidate) | `hivemq/hivemq4` | **Blocked** — no digest pinned |
| Image digest | — | **Blocked** — not pulled/verified in Task 1 |
| Authentication extension | HiveMQ Enterprise Extension for MQTT (file/JWT/OIDC as qualified) | **Blocked** — requires license + live config |
| mTLS bridge ingress | Per-edge client certificates | **Blocked** — Task 10 |
| Publish-only edge ACLs | Bridge principal publish-only; deny subscriptions | **Blocked** — live broker ACL qualification |
| Active session revocation | Admin disconnect on cert revocation | **Blocked** |
| Stable client IDs | Per-edge assigned IDs + MQTT 5 persistent session policy | **Blocked** — measured on qualified broker |
| Retained message policy | Explicit retain rules per route | **Blocked** |
| Persistent subscriptions | Deny for bridge principals | **Blocked** |
| Queue / inflight limits | Finite per-session queues | **Blocked** |
| Broker restart behaviour | Crash-after-PUBACK loss window | **Blocked** — requires fault injection |

If the candidate broker cannot pass the rows above, **stop the production broker
branch** and escalate a product/edition decision. Do not substitute Mosquitto, EMQX,
or another broker without explicit qualification.

### 4.2 HiveMQ Edge (DMZ collector)

| Field | Value | Status |
| --- | --- | --- |
| Development image | `hivemq/hivemq-edge:latest` (`docker-compose.yml`) | Floating tag — **not production-qualified** |
| Image digest | — | **Blocked** — `latest` only in dev |
| Management API | `/api/v1/auth/authenticate`, `/api/v1/management/protocol-adapters/adapters` | Documented in code; **not pinned to Edge release** |
| Supported adapter API schemas (code) | Agent: `opcua`, `modbus`, `s7`, `eip`. Local `hivemq_edge_api.py` still maps `opcua`/`s7`/`eip`. | Cloud-edge agent compiles Modbus; live Edge adapter still license/digest gated |
| Offline bridge buffering license | HiveMQ Edge persistent offline buffering ([S2](https://docs.hivemq.com/hivemq-edge/mqtt-bridging.html)) | **Blocked** — commercial license required; operator input absent |
| Edge TLS listener | `8883` mTLS for local publishers + cloud bridge | **Blocked** — not configured in dev `config.xml` |

### 4.3 Operator actions required before qualification can advance

1. Confirm HiveMQ Enterprise (central broker) license tier and extension entitlements.
2. Confirm HiveMQ Edge offline buffering license for each DMZ site requiring durable edge tier.
3. Supply digest-pinned OCI images (or offline tarballs) for the chosen Edge and broker releases.
4. Provide test CA / issuance process for mTLS (management + MQTT bridge).

## 5. Recovery point objectives (RPO) — separate boundaries

**No overall zero-loss claim from MQTT QoS alone.** Record each boundary independently.
Measured values are **not available** in Task 1.

| Boundary | Intended mechanism | Task 1 status | Notes |
| --- | --- | --- | --- |
| Edge power loss | Licensed HiveMQ Edge offline bridge buffering + disk | **Blocked** | License absent; durable edge tier unqualified. Unit tests for management agent are **not** blocked. |
| Central broker power loss | Broker persistence + bridge session policy | **Blocked** | Requires qualified `hivemq4` (or chosen edition) and crash-after-PUBACK test |
| Canonical Kafka persistence | `uns.historic-events` retained log (dev: 7 days / `604800000` ms) | **Design accepted; live RPO not measured** | At-least-once; mapper ACKs MQTT after Kafka produce in current ingest path |
| SQL outbox persistence | PostgreSQL durable outbox for HTTPS business push | **Implemented (Task 13); live RPO not measured** | `publication_outbox.py`, migration `0013`, worker + ingress tests; `202` ≠ broker/lake delivery until qualified |

Accepted RPO targets for production must be recorded after Tasks 10, 11A, 13, and 15
fault injection — not before.

## 6. Edge-to-cloud-only profile summary

Enabled:

- DMZ-initiated MQTT/TLS bridge (edge → cloud data only).
- DMZ-initiated HTTPS management (agent poll/report).
- Edge protocol adapters for qualified industrial sources.
- Optional `edge-sim` publishers → local Edge MQTT `hivemq-edge:8883` only.
- Existing central pipeline: MQTT → Kafka → historian / lake / GraphQL.

Disabled or removed from cloud runtime:

- Cloud-initiated connections to DMZ management or Edge API.
- GraphQL direct OPC UA probes and local `config.xml` writes.
- `10_uns_opcua` parallel collector in production.
- Simulators publishing directly to cloud broker addresses.
- Development floating images, public Edge console port, unencrypted MQTT `1883`.
- Cloud-to-edge MQTT application topics and device write mappings.

## 7. Exit criteria for Task 1

| Criterion | Result |
| --- | --- |
| Source baseline explicit | **Done** — sections 1–2 |
| Graphify-confirmed API/PLC/config paths | **Done** — sections 2.1–2.4 |
| Reader/lake actual readiness recorded | **Done** — section 3 |
| Product/license facts recorded or blocked | **Done** — section 4; `qualification_status: unqualified` |
| RPO boundaries separated | **Done** — section 5 |
| `release-contract.json` defined | **Done** — `deploy/release-contract.json` |

**Programme gate:** Production broker and durable edge tiers remain **unqualified**.
Proceed to Task 2 isolated harness work; do not declare production support.

## 8. Task 15 — release pipeline and fault matrix (2026-09-12)

| Field | Value |
| --- | --- |
| Date (UTC) | 2026-09-12 |
| Git branch | `feat/cloud-platform-outbound-edge` |
| Release workflow | `.github/workflows/cloud-edge-release.yml` |
| Authorized publish | `workflow_dispatch` with `publish_release=true` only |
| Local tests | Never publish manifests; CI unit job runs `-m "not integrationtest"` |

Release artifacts separate metadata (`deploy/cloud/release.json`, `deploy/edge/release.json`,
`deploy/release-contract.json`) from secrets. OCI builds use locked Dockerfiles and an
`linux/amd64` + `linux/arm64` matrix. The optional `edge-sim` overlay and four simulator
images share Dockerfiles with `deploy/test/compose.yml`.

### 8.1 Fault matrix status

| fault_id | Summary | Status | Evidence |
| --- | --- | --- | --- |
| `all_simulators_disabled` | All simulators disabled | **integration** (Linux CI) | `deploy/test/test_configuration_recovery.py` |
| `real_and_simulator_together` | Real-shaped endpoint and simulator configured together | **integration** (Linux CI) | separate revisions + fixture values |
| `edge_sim_no_plc` | No PLC hardware, edge-sim enabled | **contract** | `deploy/test/test_edge_simulation.py`, Task 11A |
| `mapping_changed_on_simulated_source` | Cloud mapping changed on a simulated source | **integration** (Linux CI) | `deploy/test/test_simulated_config_roundtrip.py` |
| `https_only_outage` | HTTPS-only outage during simulation | **integration** (Linux CI) | router `block-https` / `restore-https` |
| `cloud_management_unavailable` | Cloud management unavailable | **integration** (Linux CI) | pending until HTTPS restore |
| `vm_power_loss_during_apply` | VM power loss during apply | **contract** | `15_uns_edge_agent/test/test_journal.py` |
| `cloud_restart_after_snapshot` | Cloud/database restart after snapshot commit | **blocked** | Persistent cloud-management store not wired in qualification stubs |
| `https_response_loss_after_report` | HTTPS response loss after enrollment/report | **blocked** | Requires live agent HTTPS fault injection |
| `duplicate_cloned_agent` | Duplicate/cloned agent | **blocked** | Lease fencing requires production identity database |
| `bridge_wan_outage_edge_restart` | Bridge WAN outage plus Edge restart | **integration** (Linux CI) | `block-cloud` + `restart_edge` + lake replay |
| `broker_crash_after_puback` | Cloud MQTT crash immediately after PUBACK | **blocked** | Qualified HiveMQ broker not available in isolated profile |
| `kafka_mapper_outage_full_queue` | Kafka/mapper downtime and full broker queue | **blocked** | Production mapper backpressure not measured on stub broker |
| `store_historian_outage` | Store/historian outage | **contract** | independent lake mapper in qualification harness |
| `partial_route_acl_release` | Partial route/ACL release | **blocked** | Route release gating requires qualified broker ACL harness |
| `certificate_expiry_rotation` | Certificate expiry/revocation/rotation | **blocked** | Live mTLS revocation harness blocked until broker qualified |
| `outbox_publish_before_status_crash` | Outbox publish-before-status crash | **contract** | Task 13 worker lease/idempotency tests |
| `http_flood_oversized_config` | HTTP flood or oversized configuration | **contract** | publication API 413/503 tests |
| `two_sites_identical_local_names` | Two sites with identical local names | **blocked** | Multi-edge isolated harness not implemented |
| `unsupported_discovery_mapping` | Unsupported discovery or southbound mapping | **contract** | edge agent protocol rejection tests |

A Linux fixture **passing** does not mean Hostinger VPS, AWS EC2, clean DMZ VM, or
qualified HiveMQ Enterprise broker were deployed.

### 8.2 Measured metrics (not production SLOs)

| Metric | Intended signal | Task 15 status |
| --- | --- | --- |
| Live/catch-up bytes/sec | Bridge and mapper throughput | **Not measured** — stub topology only |
| RSS / edge buffer usable bytes | Edge bridge offline buffer headroom | **Alert contract only** — `uns_edge_bridge_buffer_bytes` |
| Broker queue headroom | Central MQTT pressure | **blocked** — qualified broker absent |
| Kafka retention / outbox disk use | Canonical log + SQL outbox budgets | **Design + alert contract** |
| Configuration latency | desired→applied lag | **Harness only** — `uns_edge_desired_applied_lag_seconds` alert |
| Restart recovery | Journal + pending desired state | **Partial** — journal unit tests; cloud restart blocked |
| Certificate renewal/revocation bounds | mTLS lifecycle | **blocked** |
| Object verification bandwidth | Backup/restore throughput | **Not measured** |

Recorded RPO/RTO values remain **null** until live fault injection on a qualified broker
and licensed edge buffer completes.

## 9. Business delivery qualification

| Path | Status | Evidence |
| --- | --- | --- |
| DMZ MQTT business cases (LIMS/MES/SAP/machine) | **integration** (Linux CI) | `deploy/test/test_business_delivery.py` |
| HTTPS outbox (`202` / `broker_accepted`) | **contract** | Task 13 unit tests; not live broker in harness |
| Historian-independent lake delivery | **contract** | qualification kafka→lake sink |
| Live vendor SAP/LIMS/MES | **Not qualified** | simulator/fixture bodies only |

HTTP `202` means stored in the platform outbox, not archived to the lake. Receipt polling
and broker acceptance are separate from Kafka/lake delivery.

## 10. Restore and cutover components

Restore verification must cover, without silently resetting Kafka offsets or discarding
unarchived records:

| restore component | Mechanism | Task 15 status |
| --- | --- | --- |
| `sql_catalog` | PostgreSQL + Timescale backups | **Documented** — `deploy/cloud` backup profile |
| `encrypted_secrets_with_keys` | Operator-supplied TLS/CA/secret keys | **Documented** — secrets outside images |
| `identity_database` | Edge enrollment + Keycloak SQL | **blocked** — not exercised in isolated harness |
| `broker_state` | Qualified HiveMQ persistence | **blocked** |
| `kafka_retained_log` | `uns.historic-events` retention | **Partial** — lake rows preserve `kafka_offset` in harness |
| `outbox_receipts` | PostgreSQL outbox terminal rows | **contract** — Task 13 |
| `edge_journal` | SQLite apply/report journal | **contract** — `15_uns_edge_agent/test/test_journal.py` |
| `object_store_lake` | MinIO/S3 lake objects | **Partial** — qualification MinIO sink only |

Isolated restoration to a **separate deployment** is an operator procedure documented in
`deploy/cloud/hostinger.md` and `deploy/cloud/aws-ec2.md`. VM snapshots alone are not
application-consistent recovery proof.

## 11. Deployment profile status

| Profile | Task 15 status | Notes |
| --- | --- | --- |
| Linux isolated fixture (`deploy/test`) | **Contract + integration CI** | Authoritative for architecture, not production broker |
| Clean DMZ VM + edge-sim → actual cloud | **Not executed** | Operator-owned per Task 11A walkthrough |
| Hostinger VPS | **Not deployed** | Runbook only (`deploy/cloud/hostinger.md`) |
| AWS EC2 | **Not deployed** | Runbook only (`deploy/cloud/aws-ec2.md`) |
| Actual HiveMQ Enterprise broker edition | **blocked** | `qualification_status: unqualified` |
| Object backend (S3/ADLS) | **Not qualified** | MinIO stub in harness |

Record `edge-sim on VM → actual cloud` acceptance separately from physical PLC/SCADA
acceptance. Simulation milestone must not be blocked on unavailable hardware.

## 12. Observability additions (Task 15)

Prometheus alert group `uns_cloud_edge` adds:

- `UnsEdgeDesiredAppliedLag`
- `UnsEdgeBridgeBufferPressure`
- `UnsPublicationOutboxBacklog`
- `UnsEdgeCertificateExpiryWarning`
- `UnsEdgeHeartbeatStale`
- `UnsEdgeBridgeDropDetected`

Grafana dashboard `platform-observability.json` adds panels for edge lag, bridge buffer,
outbox backlog, and certificate expiry. Metric series must be emitted by production edge
agent, bridge, and publication worker before alerts fire in a live deployment.

## 13. Exit criteria for Task 15

| Criterion | Result |
| --- | --- |
| Authorized release workflow with arch matrix | **Done** — `.github/workflows/cloud-edge-release.yml` |
| Fault matrix documented with blocked rows explicit | **Done** — section 8.1 |
| `deploy/test` unit + integration suites | **Done** — configuration, business, restore, observability |
| Restore components documented | **Done** — section 10 |
| Prometheus/Grafana cloud-edge signals | **Done** — alert contracts + dashboard panels |
| Measured production RPO/RTO | **Not available** — remains blocked |

**Programme gate unchanged:** `qualification_status: unqualified` until operator supplies
digest-pinned broker/edge images, licenses, and live provider deployments.

## 14. Design §11 acceptance matrix (Task 16)

Maps each row in [design §11](../superpowers/specs/2026-09-12-cloud-platform-outbound-edge-design.md#11-acceptance-criteria)
to executed test evidence, operator-run qualification, or an explicit blocked row.
**Contract** = unit/compose tests in CI. **Integration** = Linux isolated harness
(`deploy/test`, `-m integrationtest`). **Operator** = documented runbook step not yet
executed on a live VM/provider. **Blocked** = requires qualified broker, license, or
hardware not available in the programme harness.

| Design §11 scenario | Status | Evidence |
| --- | --- | --- |
| Clean DMZ VM installation | **contract + operator** | `deploy/test/test_edge_package.py`; runbook [`dmz-edge-installation.md`](../operations/dmz-edge-installation.md); live VM install **operator** |
| Real-device-ready base release | **contract** | `test_edge_package.py` (no default adapters); `test_all_simulators_disabled_base_configuration_still_works`; hivemq template has no fixture hostnames |
| Same adapters for both source types | **contract + integration** | `test_real_shaped_and_simulator_connections_use_separate_settings`; `test_simulated_config_roundtrip.py`; no reinstall path in runbooks |
| Mixed real/simulated catalog | **integration** | `test_real_shaped_and_simulator_connections_use_separate_settings`; separate connection IDs/revisions in harness |
| Hardware-free edge profile | **contract** | `deploy/test/test_edge_simulation.py`; base compose exactly two services; overlay optional `edge-sim` |
| Simulator-to-cloud data path | **integration + operator** | `test_publish_case_reaches_lake_fixture`; `test_ot_simulators_cannot_reach_cloud`; VM-to-cloud manifest **operator** |
| Cloud-to-edge configuration round trip | **integration** | `test_enroll_save_and_apply_round_trip`; `test_cloud_configuration_changes_simulated_collection`; `test_simulated_config_roundtrip.py` |
| Firewall blocks cloud-to-DMZ initiation | **integration** | `test_network_boundary.py` (`test_cloud_cannot_dial_dmz_management`, HTTPS-only outage keeps MQTT) |
| OPC UA and Modbus | **contract + integration** | `15_uns_edge_agent/test/test_protocols.py`; `test_simulated_config_roundtrip.py` (parametrized); live wire qualification **blocked** on physical devices |
| Configuration while edge offline | **integration** | `test_https_only_outage_keeps_mqtt_while_configuration_stays_pending`; `test_pending_configuration_survives_https_outage_until_restore` |
| Apply partial failure/restart | **contract + integration** | `15_uns_edge_agent/test/test_journal.py`; `test_vm_power_loss_journal_contract_is_unit_tested`; degraded status in agent reconcile tests |
| Two edges/sites | **blocked** | `two_sites_identical_local_names` in fault matrix; multi-edge harness not implemented |
| Southbound configuration attempt | **contract** | Edge agent protocol rejection tests; cloud bridge publish-only ACL config in `test_mqtt_boundary.py` (skipped live) |
| Outage plus Edge restart | **integration** | `test_bridge_wan_outage_survives_edge_restart_and_reconciles`; duplicate/gap boundaries documented, licensed buffer **blocked** |
| Central broker crash/mapper outage | **blocked** | `broker_crash_after_puback`, `kafka_mapper_outage_full_queue` fault rows; PUBACK-to-Kafka window not measured |
| Secret/certificate rotation/revocation | **blocked** | `certificate_expiry_rotation` fault row; live mTLS revocation harness requires qualified broker |
| HTTP/raw business publication | **contract + integration** | Task 13 unit tests; `deploy/test/test_business_delivery.py`; exact-body and idempotency contracts |
| Historian unavailable | **contract + integration** | `test_business_case_reaches_lake_without_cloud_local_shortcut`; historian-independent lake path in harness |
| Hostinger/AWS portability | **operator + blocked live** | `deploy/cloud/hostinger.md`, `aws-ec2.md`; `test_provider_runbooks_cover_required_operator_steps`; no live VPS/EC2 deploy executed |
| Restore/cutover | **contract + operator** | `deploy/test/test_restore.py`; backup profile documented; isolated restore **operator**; no false Kafka offset continuity (`test_restore_policy_forbids_silent_kafka_offset_reset`) |

### 14.1 Task 16 completion review

| Review item | Result |
| --- | --- |
| Credential leaks in diff | None observed in Task 16 documentation-only changes |
| Mixed user/dev artifacts in production bundles | Forbidden by `test_cloud_package.py` / `test_edge_package.py` |
| Network assumptions documented | Outbound-only matrix in design §5; runbooks name 443/8883 explicitly |
| Managed-adapter ownership | Cloud GraphQL does not write local `config.xml`; agent reconciles on edge |
| Unsafe success assertions | Qualification doc separates HTTP 202, broker acceptance, and lake delivery |
| `git diff --check` | Run at Task 16 handoff |
| Graphify AST refresh | Run at Task 16 handoff (Markdown not semantically indexed) |

### 14.2 Remaining source-specific integration work

| Area | Status |
| --- | --- |
| Physical PLC/SCADA per vendor | **Not qualified** — simulators and test servers only |
| Native SAP/LIMS/MES connectors | **Out of scope** — generic HTTPS/MQTT publication only |
| HiveMQ Enterprise broker live ACL/revocation | **Blocked** — operator license + digest |
| HiveMQ Edge offline buffering RPO | **Blocked** — commercial license |
| Multi-site edge isolation at scale | **Blocked** — second-edge harness |
| S3/ADLS production object backend | **Not qualified** — MinIO stub in harness |
| HA tier / managed cloud DB substitution | **Not included** in completion claim |

**Programme completion (Task 16):** Installable bundles, runbooks, acceptance mapping,
and isolated CI qualification are in place. Production rollout and live provider/VM
evidence remain distinct authorized operator actions while `qualification_status` stays
`unqualified`.
