# Edge simulation overlay artifacts

Hardware-free commissioning profile `edge-sim` for the DMZ edge bundle.

## Contents

| File | Purpose |
| --- | --- |
| `connections.json` | Sample OPC UA and Modbus connection inputs for cloud mutations |
| `publication-routes.yaml` | Topic filters to register before observing simulation traffic |
| `secrets/mqtt-sim.env.example` | Local MQTT username/password (copy to `mqtt-sim.env`) |
| `secrets/mqtt-tls.env.example` | TLS file paths inside simulator containers |

## Data path

```text
MQTT simulators (OEE, multi-system) --> hivemq-edge:8883 --> outbound bridge --> cloud
OPC UA / Modbus simulators <-- protocol reads <-- HiveMQ Edge (after cloud apply)
```

Simulators have no cloud broker address, cloud credentials, or cloud egress. Protocol
servers expose fixture endpoints only on the internal `sim-ot` network.

## Operator commands

After Task 11 enrollment on a Linux VM:

```bash
sudo docker compose --project-directory /opt/uns-edge \
  -f /opt/uns-edge/compose.yml \
  -f /opt/uns-edge/compose.simulation.yml \
  --profile edge-sim up -d

sudo ./verify.sh --destination /opt/uns-edge --profile edge-sim
```

Stop only the four simulator services (preserves Edge/agent volumes):

```bash
sudo docker compose --project-directory /opt/uns-edge \
  -f /opt/uns-edge/compose.yml \
  -f /opt/uns-edge/compose.simulation.yml \
  --profile edge-sim stop \
  oee-simulator multi-system-simulator opcua-simulator modbus-simulator
```

Remove simulation adapters and disable their routes through normal cloud configuration.
Never use `down -v` to leave simulation mode.
