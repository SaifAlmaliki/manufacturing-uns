# Cloud-hosted UNS with outbound-only DMZ edge management

Date: 2026-09-12

Status: Architecture approved in conversation; written design and implementation
details prepared for review. Planning only: no deployment, purchase, or cutover.

Plan: [Implementation plan](../plans/2026-09-12-cloud-platform-outbound-edge.md).

## 1. Goal and approved boundaries

Run the central UNS platform on Hostinger VPS or AWS. Deploy HiveMQ Edge and one
small UNS management agent on a Linux VM in each site's DMZ. On-premises IT installs
and enrolls that package once; platform owners subsequently configure connections
through the cloud console.

The initial rollout must be demonstrable without physical PLCs. Ship an optional
`edge-sim` profile on the same DMZ VM, reusing the current MQTT simulators and adding
protocol test servers so both upstream data and cloud-authored adapter configuration
can be exercised across the real VM-to-cloud connection.

**Real equipment support is a required implementation deliverable.** The simulator
profile supplements real PLC/SCADA connectivity; it does not replace it or permit a
simulator-only implementation. The same released HiveMQ Edge adapters, management
agent, cloud connection forms, and data pipeline serve both kinds of endpoint.
OPC UA and Modbus TCP must accept real network endpoints, device-specific security
settings, nodes/registers, and polling configuration. Existing S7/EtherNet/IP paths
must remain supported where qualified for the selected Edge release; other protocols
are enabled only when their adapters and configuration contracts are implemented.
Changing from a simulator to real equipment is an authorized connection/route
configuration and network-permission change, not an application-code change,
replacement collector, reinstall, or re-enrollment.

The user approved these boundaries:

- HiveMQ Edge collects from PLCs and permitted on-premises sources.
- All DMZ-to-cloud connections are initiated from the DMZ. No inbound cloud access
  to the VM, reverse shell, VPN, or cloud connection to the Edge management API.
- Collected MQTT publications flow edge to cloud only. MQTT acknowledgements and
  connection-control packets still return over the established connection.
- Cloud-authored configuration reaches the agent in responses to outbound HTTPS
  requests. Applying configuration and reporting results is permitted.
- Configuration includes OPC UA, Modbus, other qualified adapters, tags, and topic
  mappings. Device writes and cloud-to-edge MQTT application topics are excluded.
- The agent is the explicitly approved addition to the original Edge-only footprint.
- SAP, LIMS, MES, and other business systems publish into the central UNS, directly
  or through integration adapters appropriate to the source system.
- The edge release includes an explicitly enabled simulation profile for hardware-free
  commissioning. Simulator services run on the edge VM, not beside the cloud broker.
- Real and simulated connections may coexist on one edge, with distinct connection
  IDs, registered topics, and source identities. No global simulation mode may
  redirect a real connection or suppress real-device support.

This extends [ADR-0012](../../adr/0012-multi-system-uns-to-lake-delivery.md) and the
[multi-system delivery plan](../plans/2026-09-11-multi-system-uns-to-lake.md).
Keep MQTT as the UNS and `uns.historic-events` as the canonical internal Kafka log.
Keep independent lake, historian, and GraphQL consumers, frozen v2 routing, raw byte
fidelity, and at-least-once semantics. Business publications still require no asset.

## 2. Inspected repository baseline

Observations are from the working tree, including existing staged changes; they
are not evidence that a deployment has passed qualification.

| Current location | Deployment consequence |
| --- | --- |
| `docker-compose.yml` | Explicitly development-only; bundles Edge with central services, uses several floating images and public development ports. |
| `conf/hivemq/config.xml` | Local adapters, unencrypted MQTT listener, management listener; currently bind-mounted read-only by Compose. |
| `00_uns_config/src/uns_config/hivemq_edge_api.py` | Direct synchronous Edge calls; maps OPC UA, S7, EtherNet/IP, but not Modbus. Deletes catalog-owned adapters absent from its supplied full list. |
| `00_uns_config/src/uns_config/hivemq_edge_xml.py` | Local configuration-file rendering and editing. |
| `07_uns_graphql/src/uns_graphql/mutations/connectivity.py` | Writes local XML through `after_flush`, then directly applies to the local Edge API. Also directly browses OPC UA. |
| `07_uns_graphql/src/uns_graphql/queries/connectivity.py` | Tests, browses, and reads OPC UA endpoints from the GraphQL process. |
| `09_uns_model/src/uns_model/connectivity.py` | Shared connectivity catalog lacks the required per-edge desired/reported lifecycle. |
| `00_uns_config/src/uns_config/platform.py` | Several public URLs assume HTTP/localhost. |
| `docker-compose.yml` identity configuration | Keycloak uses `start-dev`; public issuer and Grafana URLs reference localhost. |
| `10_uns_opcua` | A separate local collector exists; it must not duplicate Edge collection in the new deployment. |
| `HiveMQ-Simulator.sh`, `conf/simulator/Dockerfile` | Existing MQTT OEE/machine publisher; `H`/`P` select the broker, and some generated payloads intentionally deviate. It is not an OPC UA/Modbus server. |
| `conf/simulator/multi_system_publishers.py`, `Dockerfile.multi-system` | Existing MQTT machine/MES/LIMS/SAP-shaped publishers; `MQTT_HOST`/`MQTT_PORT` select the broker. Local TLS/authentication and restart-safe simulation identity need extending for this profile. |

Moving the existing containers unchanged would therefore leave remote configuration,
discovery, identity URLs, credentials, persistence, and network boundaries incorrect.

## 3. Topology and hosting profiles

```text
ON-PREMISES OT / BUSINESS NETWORK
  PLCs, OPC UA servers, Modbus devices, local publishers
            ^ collection connections       | optional local MQTT publications
            | permitted by OT firewall     v
DMZ VM
  HiveMQ Edge <---- private local management API ---- UNS edge agent
       |                                               |
       | initiates MQTT/TLS                            | initiates HTTPS
       | publishes data                                | polls configuration,
       |                                               | sends reports
       +------------------- FIREWALL ------------------+
                           | established return traffic allowed
CLOUD: HOSTINGER VPS OR AWS
  Central MQTT broker                    Edge management API
       ^                                          |
       | business MQTT                            | desired/reported state
       |                                          v
  HTTPS business ingress -> durable outbox     PostgreSQL catalog
       |                        |
       +------ outbox worker ---+--> Central MQTT broker
                                           |
                                  registered ingestion
                                           |
                                  uns.historic-events
                                    /      |       \
                              historian   lake    GraphQL
                                           |
                                     raw object storage
  Console / OIDC / observability remain central.
```

### Hosting decision

Use immutable OCI images, explicit runtime configuration, persistent storage, health
checks, and reproducible release bundles. The first reference deployment is a
single Linux server using a dedicated production Compose bundle, portable between
Hostinger **VPS** and AWS **EC2**. This is a single-server availability tier, not HA.
It is not a shared-web-hosting deployment and does not require Kubernetes.

Production bundle responsibilities:

- Central application containers: existing mappers, APIs, console, OEE, and enabled
  platform services; add the edge-management API and business outbox worker.
- Central infrastructure: full production MQTT broker, Kafka, PostgreSQL/Timescale,
  required Neo4j services, production-mode identity, metrics, and HTTPS ingress.
- External raw object storage is the reference data-lake target (S3 or a qualified
  existing backend). A local object store is an isolated test option, not off-host
  disaster recovery.
- Use a full HiveMQ central broker as the reference candidate, **not HiveMQ Edge**
  as the cloud broker. The exact edition, license, image digest, authentication
  extension, and persistence behavior must pass the plan's broker qualification
  gate before being declared production-supported. No broker purchase is implied.
- Production manifests contain image digests, not source builds or `latest` tags.
  Stateful services each receive durable volumes and tested backup/restore paths.
- Server size is derived from measured data rate, retained log size, catalog size,
  active routes, and concurrent users. Do not publish an unmeasured capacity claim.

AWS managed services are a later deployment evolution, not drop-in substitutions.
Qualify Kafka semantics before adopting MSK; verify Timescale extension support
before choosing a PostgreSQL service; qualify MQTT behavior before substituting
any managed MQTT product. An HA tier needs a separate availability/capacity design.

## 4. One-time DMZ installation and ownership

Ship `deploy/edge/` as a versioned release archive. The base deployment has two
long-running services: `hivemq-edge` and `uns-edge-agent`. The optional
`compose.simulation.yml` overlay with profile `edge-sim` adds four simulator services
described below. Installation utilities are one-shot operations.

IT's initial installation sequence:

1. Create a supported Linux VM and provision measured disk/memory capacity.
2. Install Docker Engine/Compose through the organization's approved process.
3. Install a verified release archive under `/opt/uns-edge`; either pull digest-pinned
   images or import the supplied image archive if registry access is unavailable.
4. Configure approved cloud DNS names, local destination allowlists, trusted CAs,
   local Edge API credentials, and required firewall rules.
5. Start the two services with persistent volumes. Edge has no production adapter
   until configuration arrives; its management API is not published on a host port.
6. In the cloud console, an administrator creates the site's edge registration and
   a short-lived enrollment token. IT enters it through a non-echoing prompt on
   the VM, not through a command-line argument, image layer, or Compose environment.
7. Run enrollment, verify the edge identity and heartbeat in the console, then save
   the first connection. Confirm applied configuration separately from data arrival.

The agent accesses `https://hivemq-edge:8443` on a private container network with
certificate validation. This is container-to-container traffic, not `localhost`
across separate containers. Only Edge needs a published MQTT listener if local
systems publish to it; bind that listener to the intended VM interface and restrict
its clients. The agent exposes no inbound listener and has no Docker socket.

Persist Edge configuration/data/keystores and agent identity/journal on separate
volumes with explicit permissions. The Edge config directory must support its API's
persistence; do not reuse the current read-only single-file mount. Runtime Edge API
credentials stay local. Agent updates and Edge image upgrades are IT-operated release
changes; remote configuration cannot execute shell commands or replace images.

### 4.1. Hardware-free edge commissioning profile

| Profile service | Implementation | What it verifies |
| --- | --- | --- |
| `oee-simulator` | Reuse `HiveMQ-Simulator.sh` and its current image recipe, adding scoped local TLS/auth and deterministic acceptance mode. | SCADA-like MQTT machine states, counters, OEE values, retained traffic, and central live views. |
| `multi-system-simulator` | Reuse `conf/simulator/multi_system_publishers.py` and its image recipe. | Machine, MES, LIMS, and SAP-shaped publications traverse the local Edge broker before cloud routing/lake delivery. |
| `opcua-simulator` | New protocol test-server fixture, packaged in the release. | The owner adds an OPC UA connection/tags from the cloud; Edge's actual adapter reads the server. |
| `modbus-simulator` | New Modbus TCP test-server fixture, packaged in the release. | The owner adds a Modbus connection/register mapping from the cloud; Edge's actual adapter reads registers. |

The MQTT generators emulate a publishing SCADA/business application; they do not
prove industrial-protocol adapter behavior. The two protocol servers exercise that
separate path. These are test sources, not an installation of a real SCADA, SAP,
MES, or LIMS product.

Simulation-specific endpoints, node IDs, register maps, credentials, and generated
values belong only to fixture files and the optional overlay. Production adapters
must use the connection settings submitted by the owner, with the IT-approved
destination allowlist. The base release must start and configure real connections
with every simulator disabled. Tests must also cover simultaneous real-shaped
external endpoint configurations and simulator connections without cross-routing.

```text
EDGE VM, edge-sim profile
  Existing OEE and multi-system simulators -- local MQTT/TLS --+
  OPC UA test server <-- OPC UA reads -- HiveMQ Edge          |
  Modbus test server <-- Modbus reads -- HiveMQ Edge <--------+
                                           |
                                      MQTT/TLS outbound
                                           v
                                  REAL CLOUD DEPLOYMENT
                                  MQTT -> Kafka -> lake/live views

  Cloud owner saves adapter configuration
      -> agent's outbound HTTPS poll receives revision
      -> private local Edge API applies it
      -> Edge begins/changes collection from the protocol test server
      -> agent reports the applied revision to cloud
```

Use an isolated `sim-ot` container network on the VM. Simulators have no cloud
credentials, no internet/cloud egress, no host-published ports, and no Edge API
credentials. Only HiveMQ Edge joins both `sim-ot` and its cloud-facing network.
The agent stays on its private management/cloud-facing network. Allow Edge to reach
`opcua-simulator:4840` and `modbus-simulator:1502` in the simulation bootstrap
allowlist; 1502 avoids a privileged port inside the test container. Local MQTT
publishers target `hivemq-edge:8883` with locally scoped credentials, not the cloud
broker. Provision certificates with the container DNS names in their SANs.

Base installation remains simulator-free. The release archive also contains the
overlay, digest-pinned simulator images (online or offline), example cloud connection
inputs, known OPC UA node IDs/Modbus register definitions, and a step-by-step
`docs/operations/edge-simulation-demo.md` runbook. Starting simulators must not
pre-create adapters through local scripts: save the desired connections through
the actual cloud API/console to demonstrate the approved management path.

Every run uses a dedicated simulation site/namespace and a run manifest recording
edge identity, configuration revisions, route revisions, test source IDs, expected
values, and timestamps. Label test data through registered topics/routes and the
manifest; do not invent an unsupported canonical-envelope flag. Scope the existing
generators' prefixes to this namespace, preserving their application suffixes and
matching registration. Do not mix test publications into real production topics.
Add a reproducible, bounded acceptance mode while preserving the current randomized
demo mode; intentional malformed payloads run as a separate rejection scenario.
Each publisher restart gets a fresh boot ID or resumes a persisted sequence; the
existing fixed boot ID plus reset sequence cannot be used as a durable test identity.

### 4.2. Required VM-to-cloud demonstration

1. Install/enroll the edge release and start `edge-sim` on the VM; no physical PLC
   is needed. Activate simulation routes/ACLs in the cloud through the normal barrier.
2. Verify current MQTT simulator data reaches the local Edge and then central live
   views/Kafka/lake. Prove the simulator containers cannot contact the cloud directly.
3. From the cloud console, create connections to the OPC UA and Modbus test servers,
   select documented nodes/registers, and save. Record desired/applied revisions
   and actual adapter connection status. Before this action their adapter topics
   must have no fresh events for the current run.
4. Observe both protocols' known values in central live views and physical lake
   rows. For protocol sources, raw fidelity begins with the MQTT bytes generated
   by Edge; compare those bytes at local MQTT and lake, not with OPC UA/Modbus wire
   packets. Separate adapter-value correctness from payload-byte fidelity.
5. Change a tag/register selection and its MQTT mapping in the cloud. Verify the
   agent applies the next revision and new values/topics arrive upstream. For
   unsubscribed topics, allow bounded in-flight/buffered deliveries and distinguish
   old retained values/history from fresh post-apply samples.
6. Block only management HTTPS, save a configuration while offline, and verify it
   remains pending while MQTT data continues. Restore HTTPS and verify application.
   Separately interrupt MQTT and measure reconnection/backlog behavior; durable
   recovery still requires the licensed buffering qualification in section 8.
7. Restart the VM and verify identity, last applied configuration, and simulator
   identity handling. Record outcomes in the run manifest. Stop/remove only the
   simulation services when moving to real sources; preserve core state and history.

The single-VM simulated OT network demonstrates application paths and isolation,
but does not replace the separate OT-firewall or hardware qualification. The live
DMZ-to-cloud firewall/TLS/configuration path must be tested on the actual VM and
chosen cloud deployment, separately from local CI fixture results.

## 5. Firewall and connection matrix

| Initiator | Destination | Allowed purpose |
| --- | --- | --- |
| Edge | Cloud MQTT DNS, TCP 8883 | MQTT 5 over TLS 1.2/1.3, hostname verification, per-edge client certificate. |
| Agent | Cloud management DNS, TCP 443 | Enrollment over server-authenticated TLS; enrolled requests over mTLS. |
| Edge | Approved OPC UA endpoints | Explicit configured addresses/ports; 4840 is common, not a universal rule. |
| Edge | Approved Modbus TCP endpoints | Explicit configured addresses/ports; 502 by default. |
| Edge | Other qualified industrial sources | Only ports required by that adapter/site. |
| Approved local publishers | DMZ Edge MQTT listener | Optional authenticated MQTT/TLS; source-network firewall approval required. |
| VM | Approved DNS/time infrastructure | Certificate validation and stable timestamps. |
| IT installation process | Approved registry/update source | Installation and maintenance only; offline image import also supported. |

Allow established return traffic. No cloud-initiated connection into the DMZ;
no public Edge API, VM SSH, Kafka, SQL, Neo4j, metrics, or identity administration.
IT's local VM administration follows its own management-network policy. Host-level
container firewall behavior must be verified, not inferred from a UFW rule alone.

## 6. Identity, enrollment, secrets, and authorization

Use separate identities for console people, management agents, MQTT bridges, and
business publishers. Console users retain OIDC. Initial enrollment uses a 256-bit
random token, stored hashed, single use, 15-minute validity, bound to one edge/site.

The agent generates two private keys locally and submits CSRs: one for HTTPS
management, one for bridge MQTT. The cloud derives permitted certificate identity
from the registration, never from requested CSR subject claims. The issuer uses a
dedicated intermediate CA; its key is accessible only to the issuance component,
not the browser, outbox worker, or Edge. Root key custody is an operator responsibility.

Bind enrollment consumption to CSR digests transactionally. A retry with the same
token and CSRs can obtain the same issued result within the token window; changed
CSRs or a different edge are rejected. After the window, lost enrollment results
require administrator recovery, not token reuse with new keys.

Certificates last 30 days; renew after 20 days with a 24-hour overlap. Revocation
blocks management requests immediately and removes MQTT permissions/disconnects
active broker sessions through the qualified broker administration mechanism.
Renewal cannot change edge/site identity. Expired devices need a new enrollment;
do not bypass validation when disconnected longer than certificate lifetime.

TLS termination must authenticate clients and forward identity only over a private
trusted upstream; strip client-supplied identity headers. Use a separate public
enrollment hostname/listener without client-certificate requirement. Its only
unauthenticated operation is bounded token exchange. Backend services have no
public bypass port. API checks current registration/revocation on every request.

Connection secrets are write-only in console responses. Store them encrypted at
rest with an externally supplied master key/key ID. Desired-state documents carry
versioned secret references; authenticated agents fetch only secrets referenced
by their configuration. Never export full configuration secrets to audit logs or
backups without encryption. Avoid shared MQTT credentials between sites.

Initially, edge enrollment/revocation/assignment is admin-only. Engineers can manage
only explicitly granted edges; add an edge-to-user grant table rather than assuming
asset-tree permissions authorize unrelated business publications. Agent identity
authorizes only its own configuration/reports; business identity only its routes.

## 7. Desired configuration and reconciliation

The cloud stores immutable full desired snapshots per edge, with optimistic
concurrency on `(edge_id, revision)`. A console edit and the next snapshot commit
in the **same database transaction**. Saving while offline succeeds as pending.
Cloud code neither writes an Edge XML file nor performs a network call to a PLC.

Contract:

```text
EdgeConfig:
  contract_version=1, edge_id, revision, digest,
  adapters[], required_route_revision, secret_refs[], deleted_adapter_ids[]
AdapterConfig:
  adapter_id, protocol, connection, tags[], northbound_mappings[]
EdgeReport:
  edge_id, boot_id, report_sequence, desired_revision, applied_revision,
  applied_digest, phase, adapter_results[], last_error_code, versions, capabilities
```

Configuration digest is SHA-256 over a defined canonical JSON encoding excluding
the digest itself. Use UTF-8, sorted keys, compact separators, finite JSON values;
secret references and versions are included, secret values are not. Reports are
idempotent on `(edge_id, boot_id, report_sequence)` and cannot regress applied state
using a delayed report from an older session. One active management lease per edge
fences cloud-side effects; local journal and single-process lock fence local writers.
Leases last 120 seconds, renew with heartbeat, and cannot be taken over while live
without an explicit administrator action. Before local writes the agent checks it
has sufficient lease time; if renewal fails it stops starting new apply operations.
An already-issued local API call can complete after expiry, so a replacement agent
must read actual state before writing. This is not remote transactional fencing of
the HiveMQ API. A copied VM identity requires revocation/re-enrollment, not automatic
simultaneous use by two machines.

Agent polls every 15 seconds with jitter, sends a heartbeat at least every 30
seconds, and backs off transient errors to at most five minutes. Console marks
heartbeat stale after 90 seconds. These are configurable operational defaults,
not latency promises during outages. One apply at a time, 4 MiB maximum snapshot,
500 adapters, and 20,000 total tags are initial admission ceilings to qualify.
Reject larger configurations explicitly; no unbounded response or journal growth.

Apply workflow:

```text
FETCH -> validate identity/revision/digest/capabilities/local endpoint allowlist
      -> verify required cloud route/ACL revision is active
      -> persist intent in local journal
      -> read current owned adapters and capture recovery snapshot
      -> apply changed adapters/tags/northbound mappings
      -> read back and verify normalized managed configuration
      -> remove explicitly deleted owned adapters after replacements verify
      -> persist result and report
```

Never send a site-wide adapter list to another edge. Only mutate IDs owned by this
edge's catalog. Missing/corrupt/truncated desired state cannot mean "delete all";
empty configuration is an explicit authenticated revision with deletion intent.

HiveMQ's multi-request adapter API is not assumed transactional. If a write fails,
report `failed` or `degraded` with per-adapter state; attempt bounded recovery of
the touched adapters from the captured snapshot and verify the result. If recovery
fails, preserve the journal and report `degraded`; never claim the old configuration
is fully active. On restart reconcile the journal against actual API state.

Repeated same revision/digest is a no-op after readback verification. Same revision
with different digest fails. Older revisions are ignored. Rollback creates a **new,
higher revision** containing the previous desired settings. Local edits to managed
adapters are reported as drift and reconciled; unmanaged adapters remain untouched.

Bridge destinations, trusted roots, agent update behavior, and the local network
allowlist are bootstrap policy, not arbitrary adapter settings from the console.
Credential renewal is a typed agent operation, not unrestricted file replacement.
Require read-only protocol mode and empty southbound mappings. A configuration
change that enables device writes is rejected even if the Edge API supports it.

### Discovery and diagnostics

Current cloud-originated OPC browsing must be replaced. Send bounded management
jobs through the same HTTPS poll/report flow: `test_connection` and `browse_tags`.
Jobs identify a saved edge-owned connection, desired revision, expiry, and page
cursor; no arbitrary URL, script, shell, write-node, or continuous value read.
Results contain connection status/tag metadata, not a second telemetry stream.

Prefer the pinned Edge API's discovery capability. If that adapter/version lacks
it, allow manually entered tags and display "discovery unsupported". Do not silently
open a connection from the cloud or add a second PLC collector. Live values in the
console come from central MQTT/Kafka. Protocol capability checks gate which forms
and management jobs are offered; "any connection" does not mean any unimplemented
protocol. OPC UA and Modbus TCP are the first required acceptance protocols.

## 8. Data plane, routing, and delivery boundary

Configure Edge forwarded topics only, with no remote subscriptions, and deny
bridge-principal subscriptions in central broker authorization. Assign stable
per-edge client IDs and MQTT 5 persistent sessions; explicitly set clean-start,
session expiry, keepalive, QoS, retain behavior, and finite queue limits.

Preserve existing topics when already globally unique and registered. For new
sites use a registered application/site/edge prefix, for example
`plant-01/machines/edge-01/opcua/temperature`. Do not rewrite existing topics silently.
Route ownership comes from ACLs plus ADR-0012 registration, not MQTT user properties
or a claimed publisher ID. Management jobs/configuration never enter data topics.

Before enabling a new topic mapping, activate its non-overlapping central route and
broker ACLs and verify the mapper's active route revision. Only then release the
edge snapshot referencing it. Topic removal revokes publication after edge deletion
is verified; retained/history cleanup is a separate explicit operation. Source/app/
schema changes get a new registration rather than changing already accepted events.

Distinguish each boundary:

1. An adapter sample is not a durable historic record merely because it exists.
2. MQTT PUBACK confirms the receiving broker's protocol acceptance, not Kafka/lake
   persistence and not necessarily synchronous disk persistence.
3. Existing MQTT ingestion confirms canonical Kafka delivery before its own MQTT
   acknowledgement. This does not retroactively extend that guarantee to an earlier
   edge-to-broker PUBACK.
4. Lake verification precedes Kafka offset commit as specified by ADR-0012.

HiveMQ currently documents persistent offline **bridge** buffering as commercially
licensed [S2]. Require the licensed feature and real restart/outage tests for the
durable edge tier. If unavailable, mark that tier unqualified; do not silently add
a custom spool or describe QoS/session settings as equivalent disk buffering.
Test central broker crash-after-PUBACK and mapper downtime separately. If its
acknowledged-message loss window is nonzero, report it explicitly and require an
accepted RPO or a different qualified broker configuration before production.

Define supported outage duration from measured usable buffer bytes divided by
measured incoming bytes/second (including overhead), then apply a safety margin.
Catch-up throughput must exceed concurrent live ingress. Queue overflow, full disk,
session expiry, and Kafka retention gaps must be observable. PLC values never
sampled, overwritten at source, or expired from every buffer cannot be replayed.

## 9. Business-system connectivity

Support two generic push boundaries:

- Direct MQTT/TLS publishers use registered raw or `uns-publication-v1` routes.
- An HTTPS push endpoint accepts original body bytes for a registered HTTP route
  and stores them in a bounded durable PostgreSQL outbox. An independent worker
  publishes an explicit wrapper to central MQTT and confirms broker acceptance.

HTTP `202` means **stored in the platform outbox**, not archived to the lake.
Reject authentication/ownership errors before storing. Body and fully encoded
envelope size must fit ADR-0012 limits. Idempotency is scoped to publisher and route:
same key/body/metadata returns the same receipt; changed content returns `409`.
Require a stable publisher key for retryable HTTP delivery. Persist a wrapper once,
with boot ID derived from the receipt UUID and sequence zero; retries use identical
bytes and source identity. Kafka/lake can still contain duplicates.

Outbox workers use leased rows, bounded batches, retry/backoff, and confirmed MQTT
QoS 1 completion. A worker crash after publish may repeat a message. Expose receipt
status as `queued`, `broker_accepted`, or `failed`; do not invent `lake_delivered`
without a downstream receipt mechanism. Bound disk use and reject new admissions
with retryable `503` before capacity exhaustion. Retain terminal receipt/idempotency
records for a documented seven-day window; beyond it a repeated key is new work.

An on-premises SAP/MES/LIMS system can use its own integration middleware to push
HTTPS/MQTT outward, or publish locally to Edge for forwarding. Such middleware is
source-system infrastructure, not a new mandatory agent on the DMZ VM. SAP product,
LIMS vendor, MES version, licensing, event/export APIs, and authentication differ;
native vendor connectors are separate source-specific follow-ups. Generic push
qualification must not be described as universal SAP/LIMS/MES connector support.

## 10. Production operations and migration

- Replace localhost public URLs, development OIDC startup, public dependency ports,
  shared default passwords, and mutable image tags in the production bundle.
- Keep runtime writable state outside application images. Inventory hierarchy-file
  mutation and all other writable config paths; mount only their owned state or
  migrate ownership to SQL. Initially keep such writers single-replica.
- Restrict health endpoints; separate liveness from dependency/readiness checks.
  Metrics include edge heartbeat age, desired/applied lag, partial applies, bridge
  backlog/drops, certificate expiry, outbox backlog, Kafka lag, and verified lake rows.
- Back up catalog/identity/secret keys and required state; restore to an isolated
  deployment and verify configuration revisions, credentials, and consumer positions.
  Volumes and VM snapshots alone are not proof of application-consistent recovery.
- First install cloud infrastructure and compatible readers, then enroll one canary
  DMZ edge. Migrate its catalog explicitly and verify data/configuration before more
  sites. Assign every connection to an edge; never auto-assign all legacy rows.
- Fence the old collector/bridge before activating the new publisher for the same
  source. Preserve source identity and existing log history; copying Kafka offsets
  to a different Kafka cluster does not preserve their meaning. For initial moves,
  drain/archive the old stream, record the cutover boundary, and start a separately
  identified cloud stream unless a qualified cluster migration is performed.
- Rollback configuration through new revisions. Rollback deployment through pinned
  releases with compatible SQL/envelope readers. Data already accepted is retained.
- Hostinger/AWS provisioning, licenses, DNS, CA custody, firewall changes, and first
  enrollment require IT/operator action. The implementation builds the artifacts and
  verifies them in isolation; it does not authorize production changes.

## 11. Acceptance criteria

| Scenario | Required evidence |
| --- | --- |
| Clean DMZ VM installation | Verified archive/images, boot persistence, enrollment, no inbound agent/API port. |
| Real-device-ready base release | With all simulators disabled, the normal cloud workflow accepts arbitrary authorized OPC UA/Modbus endpoints and device settings; no fixture hostname/node/register assumptions in production code. |
| Same adapters for both source types | Both use the released adapter/configuration/data path. Switching endpoint settings or adding a real connection requires no code changes, reinstall, or re-enrollment. |
| Mixed real/simulated catalog | Distinct connection IDs, routes, identities, and per-connection state prevent collisions and cross-routing. |
| Hardware-free edge profile | Existing OEE/multi-system publishers plus OPC UA/Modbus test servers run only on the edge VM; base profile contains no simulators. |
| Simulator-to-cloud data path | Local Edge MQTT receipt, central Kafka/live views, and physical lake rows correlate to the run manifest; no simulator-to-cloud bypass. |
| Cloud-to-edge configuration round trip | Cloud-created OPC UA/Modbus connections and a later mapping change produce verified applied revisions and corresponding new upstream values/topics. |
| Firewall blocks cloud-to-DMZ initiation | Configuration still applies and data reaches central UNS. |
| OPC UA and Modbus | Each can be configured remotely and produces a registered lake record. |
| Configuration while edge offline | Save is pending; applies after recovery with correct revision. |
| Apply partial failure/restart | Actual state and recovery journal match reported failed/degraded status. |
| Two edges/sites | No cross-edge reads, secrets, adapter deletion, topic publication, or jobs. |
| Southbound configuration attempt | Rejected; no device writes and no cloud MQTT application delivery. |
| Outage plus Edge restart | Qualified persisted backlog drains with documented duplicates and no unexplained gaps. |
| Central broker crash/mapper outage | PUBACK-to-Kafka loss window measured; supported RPO explicitly recorded. |
| Secret/certificate rotation/revocation | Same authorized identity; old credentials lose access within documented bounds. |
| HTTP/raw business publication | Exact body bytes, registered metadata, idempotent receipt, bounded outage recovery. |
| Historian unavailable | Machine, SAP-shaped, LIMS-shaped, and MES-shaped fixtures still reach raw lake. |
| Hostinger/AWS portability | Same release runs on qualified Linux target; each actual provider test and actual edge-VM simulation run reported separately. |
| Restore/cutover | Isolated restoration works; no false continuity claim across Kafka clusters. |

## 12. Sources and qualification limits

Primary documentation consulted on 2026-09-12. Context7 authentication was unavailable;
official documentation was retrieved directly instead. Re-check against pinned
versions at execution; current web documentation is not a runtime qualification.

- **S1:** [HiveMQ Edge REST API](https://docs.hivemq.com/hivemq-edge/api-configuration.html)
  — local adapter/bridge management and authentication.
- **S2:** [HiveMQ Edge MQTT bridges](https://docs.hivemq.com/hivemq-edge/mqtt-bridging.html)
  — forwarding versus remote subscriptions, TLS/mTLS, sessions, retain behavior,
  and commercial licensing for persistent offline bridge buffering.
- **S3:** [HiveMQ Edge protocol adapters](https://docs.hivemq.com/hivemq-edge/protocol-adapters.html)
  — version-dependent protocol support and northbound/southbound configuration.
- **S4:** [Hostinger VPS Docker deployment](https://www.hostinger.com/support/12040815-how-to-deploy-your-first-container-with-hostinger-docker-manager/)
  — VPS-based Compose deployment, volumes, ports, restart policies.

No resource sizing, license entitlement, live vendor connector, provider deployment,
or zero-loss guarantee has been verified by writing this design.
