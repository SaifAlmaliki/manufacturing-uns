# DMZ edge installation

Install the outbound-only HiveMQ Edge collector and UNS edge management agent on a
Linux VM in the site DMZ. The base bundle contains exactly two long-running services:
`hivemq-edge` and `uns-edge-agent`. Simulators are not part of the base
release; use the optional `edge-sim` overlay from Task 11A when hardware-free
commissioning is required.

## Prerequisites

- Supported Linux VM with Docker Engine and the Docker Compose plugin installed through
  the organization's approved process.
- Outbound firewall permission from the DMZ to the cloud management hostname on TCP
  443 and the cloud MQTT hostname on TCP 8883.
- A verified release archive extracted on the VM. Do not download or execute
  installation scripts from the network; use only the bundle supplied by platform
  owners and verify its `release.json` digests before installation.
- Either registry access to pull digest-pinned images, or a verified offline image
  archive imported with `docker load`.

## Install

From the extracted verified bundle:

```bash
sudo ./install.sh --destination /opt/uns-edge
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml up -d
```

`install.sh` checks Linux, Docker/Compose availability, free disk, and trusted
`release.json` image digests. Re-running preserves existing `agent.env`, secrets,
rendered HiveMQ configuration, and named Docker volumes.

Configure cloud DNS names, trusted CAs, local destination allowlists, and Edge API
credentials from administrator-supplied files. Copy `agent.yaml.example` values into
`agent.env` and populate `secrets/edge-api.env` locally. Do not place enrollment
tokens or API passwords in Compose environment variables or image layers.

## Enroll

In the cloud console, create the site edge registration and a short-lived enrollment
token. On the VM:

```bash
sudo docker compose --project-directory /opt/uns-edge -f /opt/uns-edge/compose.yml exec uns-edge-agent uns_edge_enroll
```

The enrollment command prompts for the single-use token without echoing it.

## Verify

```bash
sudo ./verify.sh --destination /opt/uns-edge
```

Verification checks Compose syntax, confirms both services are running, and asserts
that neither the Edge admin API nor the agent publishes a host listener.

## Upgrade

```bash
sudo ./upgrade.sh --destination /opt/uns-edge --release <release_id>
```

`upgrade.sh` requires a named release directory bundled under `releases/` and creates a
timestamped backup of configuration and secrets before applying the new manifest.

## Data flow

All plant and simulator traffic follows **source → edge → cloud**. MQTT publishers
and protocol adapters terminate on the local Edge broker. Only HiveMQ Edge initiates
the outbound MQTT/TLS bridge to the central broker. The agent initiates outbound HTTPS
management traffic only.

## Persistence

| Component | Volume | Purpose |
| --- | --- | --- |
| HiveMQ Edge | `edge-config` | Writable configuration directory for API-managed changes |
| HiveMQ Edge | `edge-data` | Broker persistence |
| HiveMQ Edge | `edge-bridge` | Licensed offline bridge buffer |
| UNS edge agent | `agent-data` | Journal, enrollment keys, and credential store |

The Edge management API listens on `https://hivemq-edge:8443` inside the private
`edge-internal` container network. It is not published on a host port in the base
bundle. Local MQTT publishers may require a host-bound `8883` listener; restrict that
binding to the approved VM interface and OT firewall policy separately from this
bundle.

## Optional simulation overlay

Task 11A adds `compose.simulation.yml` with profile `edge-sim` for
hardware-free commissioning. The base installation remains simulator-free and must
start real connections without enabling that overlay.

Use the simulation overlay for the **initial canary** when physical PLCs are
unavailable. See [`edge-simulation-demo.md`](./edge-simulation-demo.md) for the
VM-to-cloud walkthrough. After qualification evidence is recorded, stop only the
four simulator services and add real PLC connections through the cloud console—no
reinstall, re-enrollment, or image change is required.

## Canary enrollment

1. Platform admin registers one site edge in the cloud console and generates a
   single-use enrollment token (15-minute validity, bound to one edge).
2. Site IT completes base install and outbound firewall approval.
3. Run `uns_edge_enroll` once; the agent stores issued certificates in `agent-data`.
4. Platform admin assigns connections to this edge only; never auto-assign all
   legacy catalog rows.
5. Activate simulation or production routes and ACLs before expecting upstream data.

Rebooting the VM does not repeat enrollment. Lost enrollment results after the token
window require a new token from the platform admin, not CSR reuse with changed keys.

## Legacy migration on site

When replacing a local collector, parallel `opcua_client`, or old MQTT bridge:

- Stop the legacy publisher before the edge bridge carries the same source.
- Migrate catalog connections individually in the cloud console with stable IDs where
  possible.
- Record legacy Kafka topic/partition/offset cutover coordinates separately from the
  new cloud stream; offset numbers are not portable across clusters.

## IT recovery

| Scenario | Site administrator | Platform admin |
| --- | --- | --- |
| Failed upgrade | Restore from `upgrade.sh` backup; re-run upgrade with prior release ID | Supply compatible pinned release manifest |
| Full disk | Free space on data volume; inspect `edge-data`, `edge-bridge`, `agent-data` | Monitor bridge-buffer and heartbeat alerts |
| Stolen/lost agent identity | Wipe `agent-data` volume after local approval | Revoke edge registration and certificates |
| Expired certificate (long offline) | Re-enroll with new token | Issue enrollment token; verify revocation of old cert |
| Partial apply | Read agent journal and Edge connection status via cloud console | Publish corrective desired revision |
| DNS/CA rotation | Update trusted CA files and cloud hostnames in `agent.env` | Coordinate issuance and public DNS cutover |
| Unavailable PLC/vendor endpoint | Verify OT firewall and endpoint reachability | Leave connection pending/degraded; do not delete applied revision |

Package layout and verified commands: [`deploy/edge/README.md`](../../deploy/edge/README.md).
