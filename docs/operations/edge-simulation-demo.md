# Edge simulation demonstration

Hardware-free commissioning walkthrough for the `edge-sim` overlay on an enrolled DMZ
edge VM. CI simulation validates contracts; record VM-to-cloud evidence separately.

## Prerequisites

- Task 11 base bundle installed and enrolled at `/opt/uns-edge`
- Simulation routes from `deploy/edge/simulation/publication-routes.yaml` activated in the cloud console
- Local MQTT simulator credentials and TLS trust files under `simulation/secrets/`
- Outbound HTTPS (443) and MQTT/TLS (8883) allowed from the DMZ to the real cloud

## Start simulation overlay

```bash
sudo docker compose --project-directory /opt/uns-edge \
  -f /opt/uns-edge/compose.yml \
  -f /opt/uns-edge/compose.simulation.yml \
  --profile edge-sim up -d

sudo ./verify.sh --destination /opt/uns-edge --profile edge-sim
```

`verify.sh` checks six running services, internal `sim-ot` networking, local-only MQTT
destinations (`hivemq-edge:8883`), and absence of cloud broker references on simulators.

## Observe MQTT generators

Without cloud protocol configuration:

- OEE simulator publishes under `Enterprise/EdgeSimulation/Production/#`
- Multi-system simulator publishes MES/LIMS/SAP-shaped topics under `Enterprise/EdgeSimulation/#`

Confirm values in central live views and the physical lake. Firewall evidence must show
simulator containers cannot reach the cloud broker directly.

## Add OPC UA and Modbus from the cloud console

Submit the sample inputs from `deploy/edge/simulation/connections.json` through normal
cloud mutations (do not install adapters with local scripts). Record desired and applied
revisions. Before configuration, OPC UA / Modbus adapter topics must have no fresh events
for the current run.

After apply:

- OPC UA reads `opc.tcp://opcua-simulator:4840/uns-sim/` (`urn:uns:edge-simulation`)
- Modbus reads `modbus-simulator:1502` unit ID 1, zero-based holding registers 0–2

## Change mappings

Save a remapped connection (see `remapped` sections in `connections.json`). Confirm a
newer revision applies and values follow the updated topic/register selection.

## Resilience checks

1. Interrupt outbound HTTPS only, save a pending revision, restore HTTPS, confirm apply.
2. Separately interrupt outbound MQTT, restore, confirm bridge catch-up.
3. Exclude retained bootstrap and bounded pre-change backlog when verifying stopped mappings.

## Stop simulation only

```bash
sudo docker compose --project-directory /opt/uns-edge \
  -f /opt/uns-edge/compose.yml \
  -f /opt/uns-edge/compose.simulation.yml \
  --profile edge-sim stop \
  oee-simulator multi-system-simulator opcua-simulator modbus-simulator
```

Remove simulation adapters and disable routes through normal cloud configuration. Never
use `down -v` to leave simulation mode.

## Add a real PLC alongside simulators

Approve the PLC destination in the OT firewall allowlist, enter its protocol/security/node
or register settings in the cloud console, activate distinct routes, and observe its own
applied status. No application-code change, reinstall, re-enrollment, or global redirect
is required.

## Evidence to record (VM acceptance)

Host/provider, run ID, configuration revisions, source values, local/cloud timestamps,
Kafka coordinates, lake paths, byte comparisons between Edge MQTT and `original_payload`,
firewall counters, and screenshots of live values plus applied status.
