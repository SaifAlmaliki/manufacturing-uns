# DMZ edge production bundle

Outbound-only HiveMQ Edge collector and UNS edge management agent for site DMZ VMs.
Exactly two long-running services in the base profile: `hivemq-edge` and
`uns-edge-agent`.

## Contents

| Path | Purpose |
| --- | --- |
| `compose.yml` | Base edge + agent services, durable volumes, no host admin API |
| `compose.simulation.yml` | Optional `edge-sim` overlay (Task 11A) — not part of base release |
| `release.json` | Digest-pinned images and qualification status |
| `install.sh` / `verify.sh` / `upgrade.sh` | Install, health check, pinned upgrade with backup |
| `agent.yaml.example` / `agent.env.example` | Agent configuration templates |
| `secrets/edge-api.env.example` | Edge API credentials (local file, not in Compose env) |
| `hivemq/config.xml.template` | Outbound bridge + private TLS admin API template |
| `simulation/` | Hardware-free commissioning artifacts (see nested README) |

## Prerequisites

- Linux VM with Docker Engine and Compose plugin
- Outbound DMZ firewall: cloud management TCP 443, cloud MQTT TCP 8883
- Verified release archive (check `release.json` digests before install)
- HiveMQ Edge production digest and offline-buffering license (operator-supplied)
- OT firewall approval for each configured PLC/protocol destination

## Install, enroll, verify

```bash
sudo ./install.sh --destination /opt/uns-edge
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml up -d
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml exec uns-edge-agent uns_edge_enroll
sudo ./verify.sh --destination /opt/uns-edge
```

Operator runbooks:

- [`docs/operations/dmz-edge-installation.md`](../../docs/operations/dmz-edge-installation.md)
- [`docs/operations/edge-simulation-demo.md`](../../docs/operations/edge-simulation-demo.md) (initial canary with `edge-sim`)

Hardware-free overlay:

```bash
sudo docker compose --project-directory /opt/uns-edge \
  -f /opt/uns-edge/compose.yml \
  -f /opt/uns-edge/compose.simulation.yml \
  --profile edge-sim up -d
sudo ./verify.sh --destination /opt/uns-edge --profile edge-sim
```

## Upgrade

```bash
sudo ./upgrade.sh --destination /opt/uns-edge --release <release_id>
```

Creates a timestamped backup of configuration and secrets before applying a named
release under `releases/`. Rollback uses a compatible pinned release — no automatic
destructive downgrade.

## Data path

Local MQTT and protocol adapters terminate on HiveMQ Edge. Only Edge initiates the
outbound MQTT/TLS bridge; only the agent initiates outbound HTTPS management. No
inbound agent or Edge admin port is published on the host in the base bundle.

## Persistence

| Volume | Purpose |
| --- | --- |
| `edge-config` | Writable HiveMQ configuration |
| `edge-data` | Broker persistence |
| `edge-bridge` | Licensed offline bridge buffer |
| `agent-data` | Enrollment keys, journal, credential store |

Reboot does not trigger re-enrollment.

## Release and qualification

| Item | Location |
| --- | --- |
| Simulation overlay docs | [`simulation/README.md`](simulation/README.md) |
| Qualification report | [`docs/benchmarks/cloud-edge-qualification.md`](../../docs/benchmarks/cloud-edge-qualification.md) |
| Contract tests | `deploy/test/test_edge_package.py`, `test_edge_simulation.py` |
