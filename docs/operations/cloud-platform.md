# Cloud platform operations

Operate the central UNS platform from the production bundle in `deploy/cloud/`.
Simulators, HiveMQ Edge, and PLC collectors run only on DMZ edge VMs (`deploy/edge/`).
All plant traffic follows **source → edge → cloud**.

## Bundle contents

| Path | Purpose |
| --- | --- |
| `compose.yml` | Digest-pinned production services, private dependency network, public proxy and MQTT TLS only |
| `settings.yaml.example` | Runtime configuration template; copy to `settings.yaml` |
| `release.json` | Image digests, contract/envelope versions, capacity budget, qualification status |
| `validate.py` | Pre-flight checks for TLS material, HTTPS origin, broker qualification, and disk budget |
| `proxy/nginx.conf` | HTTPS/WSS console routing, separate enrollment and mTLS management server blocks |
| `broker/` | Qualified central HiveMQ broker profile (Task 10) |
| `hostinger.md` / `aws-ec2.md` | Provider-specific provisioning runbooks |

## Public surface

| Endpoint | Purpose |
| --- | --- |
| `https://uns.example.com/` | Console SPA |
| `https://uns.example.com/graphql` | GraphQL API and subscriptions |
| `https://uns.example.com/grafana/` | Embedded Grafana dashboards |
| `https://uns.example.com/auth/` | OIDC (single public issuer) |
| `https://enroll.uns.example.com/` | One-time edge enrollment (server TLS only) |
| `https://edge-mgmt.uns.example.com/` | Edge management API (mTLS, trusted-proxy headers) |
| `mqtt.uns.example.com:8883` | Central MQTT TLS (terminates at the broker, not HTTP proxy) |

Private ports (Kafka, SQL, Neo4j, Prometheus, internal GraphQL `:8000`, Grafana `:3000`,
Keycloak `:8080`) stay off the host firewall.

## Writable state inventory

| Component | Owner | Notes |
| --- | --- | --- |
| Timescale/Postgres | SQL services | Catalog, historian, Keycloak DB, route releases |
| Neo4j | `graphdb_client` | Graph projection |
| Kafka | `uns_kafka_broker` | Canonical `uns.historic-events` log |
| HiveMQ broker | `uns_mqtt_broker` | Sessions, ACL material, persistence |
| Grafana | `uns_grafana` | Dashboard state |
| Hierarchy edits | GraphQL/console | `settings.yaml` hierarchy block when used |
| Edge CA/keys | GraphQL edge issuer | Enrollment and renewal only |
| Object store | `datalake_mapper` | External S3-compatible lake target |

Keep hierarchy/config writers single-replica until ownership is migrated fully into
SQL. Kafka consumers scale only after partition ownership and client IDs are qualified;
the reference bundle does not enable blanket autoscaling.

## Start and verify

```bash
cd /opt/uns-cloud
cp settings.yaml.example settings.yaml
# populate secrets/runtime.env and TLS directories
python3 validate.py
docker compose --env-file secrets/runtime.env -f compose.yml config --quiet
docker compose --env-file secrets/runtime.env -f compose.yml up -d
```

Verify console sign-in, Grafana embed, edge enrollment, MQTT TLS from a DMZ VM, and
route-release activation after publishing a new publication route.

## Backups

Run encrypted off-host backups with the `backup` profile:

```bash
docker compose --env-file secrets/runtime.env --profile backup -f compose.yml run --rm cloud_backup
```

Configure `secrets/backup.env` with object-store credentials. `release.json` declares
minimum disk and Kafka retention budgets; `validate.py` rejects undersized hosts.

## Provider runbooks

- Hostinger VPS: [`deploy/cloud/hostinger.md`](../../deploy/cloud/hostinger.md)
- AWS EC2: [`deploy/cloud/aws-ec2.md`](../../deploy/cloud/aws-ec2.md)

Both providers use the same images and contracts. DNS, TLS, credentials, licenses, and
first enrollment remain operator actions.

## Failure domain

The reference deployment is a **single-server** availability tier, **not HA**. Loss of
the host affects console access, MQTT ingestion, SQL, Kafka, and routing together.
Managed cloud databases or brokers are not drop-in replacements without separate
qualification.

## Simulation routes

Cloud simulation **routes** may exist for qualification, but cloud-local simulator
containers are forbidden. Hardware-free commissioning uses the edge `edge-sim` overlay
(Task 11A) on the DMZ VM only.

## Canary migration sequence

Production cutover is an authorized operator action. Follow this order and named
ownership; do not auto-assign every legacy catalog row to the first enrolled edge.

| Step | Owner | Action |
| --- | --- | --- |
| 1 | Cloud IT | Provision server, DNS, TLS, secrets, license, and encrypted backups; install a qualified release from the verified archive |
| 2 | Platform admin | Verify readers and publication routes; register **one** canary edge; issue a single-use enrollment token |
| 3 | Site IT | Allow DMZ egress to cloud management (443) and MQTT (8883); approve OT destinations; install and enroll the DMZ release |
| 4 | Platform admin | Assign canary connections explicitly; activate routes and ACLs; publish a route-release snapshot |
| 5 | Edge agent | Retrieve desired state, apply locally, report applied/health status |
| 6 | Operator | Reconcile live MQTT, Kafka coordinates, and lake rows; approve rollout to the next edge only after evidence |

Start the initial canary with the edge `edge-sim` profile when physical PLCs are
unavailable. Complete the real VM-to-cloud walkthrough in
[`edge-simulation-demo.md`](./edge-simulation-demo.md) before scheduling real-source
migration. Switching from simulation to real connections uses normal cloud
configuration only—no reinstall, re-enrollment, or bundle change.

## Legacy collector and stream cutover

Before activating the new edge publisher for a source that an old local collector or
bridge already serves:

1. **Fence the old path** — stop or disable the legacy collector, local bridge, or
   development `opcua_client` profile so it cannot publish duplicate topics.
2. **Migrate catalog rows explicitly** — assign each connection to an edge in the
   console; never bulk-import legacy rows without per-connection review.
3. **Preserve stable source identity** — keep connection IDs, route principals, and
   lake metadata keys where possible so downstream readers stay compatible.
4. **Handle legacy topics** — register new routes or remap topics deliberately; do not
   assume topic strings from the old stack apply unchanged.
5. **Drain the old Kafka stream** — archive or drain the previous cluster/topic, record
   final offset and timestamp coordinates, then treat the cloud stream as a **new
   transport namespace**. Copying offset numbers across clusters is not proof of
   continuity.

Keep old compatible readers and retained data until the rollout and retention window
ends. Rollback uses a new desired revision or a compatible pinned release; there is
no automatic destructive migration downgrade.

## IT recovery matrix

| Scenario | Local administrator (site/cloud VM) | Cloud console / platform admin |
| --- | --- | --- |
| Lost cloud VM | Restore from encrypted backup to an isolated deployment; reattach DNS/TLS | Re-issue enrollment tokens only after identity store restore; verify route releases |
| Stolen edge identity | Revoke edge registration and bridge certificate; wipe agent volume on site | Revoke certificates, disconnect MQTT sessions, block management mTLS |
| Long-offline expired cert | Re-enroll with a new token after wiping compromised material if required | Issue new enrollment token; do not bypass expiry validation |
| Failed upgrade | Run `upgrade.sh` rollback from timestamped backup under `/opt/uns-edge` or cloud release directory | Pin previous qualified release; publish compatible desired revision |
| Full disk | Expand volume or prune non-state logs; verify bridge buffer and journal paths | Review capacity alerts; pause new route activations until headroom returns |
| DNS or CA change | Update trust bundles and agent/broker hostname settings locally | Update public URLs, enrollment hostname, and issuance CA in platform settings |
| Partial apply / degraded edge | Inspect agent journal and Edge applied status; retry after fixing OT reachability | Inspect desired/applied lag; publish corrective revision; do not assume save == applied |
| Unavailable vendor source | Confirm OT firewall and endpoint health locally | Mark connection degraded; keep last applied revision until source returns |

Edge reboot does **not** trigger re-enrollment. Identity material persists in the
agent volume and HiveMQ Edge configuration volume.

## Release artifacts

| Artifact | Location |
| --- | --- |
| Cloud bundle | `deploy/cloud/` — `release.json`, `compose.yml`, `validate.py` |
| Edge bundle | `deploy/edge/` — `release.json`, `install.sh`, `verify.sh`, `upgrade.sh` |
| Contract gate | `deploy/release-contract.json` |
| Authorized publish | `.github/workflows/cloud-edge-release.yml` (`workflow_dispatch`, `publish_release=true`) |

Replace placeholder digests in `release.json` with verified values before installation.
See [`deploy/cloud/README.md`](../../deploy/cloud/README.md) and provider runbooks above.
