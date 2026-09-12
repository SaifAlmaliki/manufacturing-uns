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
