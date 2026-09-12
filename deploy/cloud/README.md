# Cloud production bundle

Central UNS platform for outbound-only edge ingestion. Plant traffic follows
**source → edge → cloud**. This bundle does not run HiveMQ Edge, simulators, or
site collectors.

## Contents

| Path | Purpose |
| --- | --- |
| `compose.yml` | Digest-pinned services, private dependency network, public proxy + MQTT TLS only |
| `settings.yaml.example` | Runtime template — copy to `settings.yaml` |
| `release.json` | Image digests, envelope version, capacity budget, qualification status |
| `validate.py` | Pre-flight TLS, HTTPS origin, broker gate, disk budget |
| `proxy/nginx.conf` | Console, enrollment (server TLS), management (mTLS) |
| `broker/` | Central HiveMQ broker profile (`isolated-qualification` until operator qualifies) |
| `hostinger.md` / `aws-ec2.md` | Provider provisioning runbooks |

## Prerequisites

- Linux host meeting `release.json` disk budgets
- DNS for console, enrollment, management, and MQTT hostnames
- TLS material, OIDC, SQL/Neo4j/Kafka secrets outside images
- HiveMQ Enterprise broker license and digest-pinned image (operator-supplied)
- Compatible readers for envelope v2 (see `deploy/release-contract.json`)

## Install and verify

```bash
cd /opt/uns-cloud
cp settings.yaml.example settings.yaml
# populate secrets/runtime.env and TLS directories from operator vault
python3 validate.py
docker compose --env-file secrets/runtime.env -f compose.yml config --quiet
docker compose --env-file secrets/runtime.env -f compose.yml up -d
```

Operator runbook: [`docs/operations/cloud-platform.md`](../../docs/operations/cloud-platform.md).

Backups:

```bash
docker compose --env-file secrets/runtime.env --profile backup -f compose.yml run --rm cloud_backup
```

## Release and qualification

| Item | Location |
| --- | --- |
| Contract gate | [`deploy/release-contract.json`](../release-contract.json) |
| Qualification report | [`docs/benchmarks/cloud-edge-qualification.md`](../../docs/benchmarks/cloud-edge-qualification.md) |
| CI workflow | [`.github/workflows/cloud-edge-release.yml`](../../.github/workflows/cloud-edge-release.yml) |

Authorized manifest publish: GitHub Actions `workflow_dispatch` with
`publish_release=true` only. Local development never publishes production manifests.

## Supported protocols (edge-side)

OPC UA, Modbus TCP, S7, and EtherNet/IP are configured on DMZ edges remotely.
Cloud GraphQL does not open wire-level plant connections.

## Failure domain

Single-server availability tier — not HA. Loss of the host affects console, MQTT,
SQL, Kafka, and routing together.
