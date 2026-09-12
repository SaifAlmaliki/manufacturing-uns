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
