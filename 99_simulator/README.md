# UNS Simulator (99_simulator)

A lightweight MQTT device simulator used to generate synthetic device data for the Unified Namespace (UNS) project. Use this module to exercise MQTT consumers (graphdb, historian, Kafka bridge, SparkplugB mappers, etc.) with configurable device/metric payloads.

Features

- Configurable device templates and randomized metric values
- Publishes messages to MQTT broker(s) using settings from the repository-root [`conf/settings.yaml`](../conf/settings.yaml)
- Docker Compose service (`uns_simulator`) so it starts the same way on every OS
- Optional local CLI for development
- Unit tests under test/

Repository layout

- Platform config lives at the repository root, not in this module:
  - [`../conf/settings.yaml`](../conf/settings.yaml) — shared settings; simulator overrides are under the Dynaconf `simulator` environment
  - [`../conf/.secrets_template.yaml`](../conf/.secrets_template.yaml) — template for secrets
- src/uns_simulator/
  - config.py — configuration loader ([src/uns_simulator/config.py](src/uns_simulator/config.py))
  - devices.py — device template / helper functions ([src/uns_simulator/devices.py](src/uns_simulator/devices.py))
  - models.py — data models used by the simulator ([src/uns_simulator/models.py](src/uns_simulator/models.py))
  - simulator.py — core simulator implementation ([src/uns_simulator/simulator.py](src/uns_simulator/simulator.py))
  - main.py — CLI / entrypoint ([src/uns_simulator/main.py](src/uns_simulator/main.py))
- Dockerfile — container image, same pattern as the other Python UNS services
- test/ — unit tests ([test/](test/))

Quick start (Docker Compose)

The simulator is part of the repository-root [`docker-compose.yml`](../docker-compose.yml). From the repository root:

```bash
docker compose up -d --build
```

That starts the MQTT broker **and** the simulator (plus the rest of the local stack). Same command on Windows, macOS, and Linux.

Start or stop **only** the simulator:

```bash
docker compose up -d uns_simulator
docker compose stop uns_simulator
docker compose start uns_simulator
docker compose logs -f uns_simulator
```

`docker compose up -d uns_simulator` also starts `uns_mqtt_broker` when it is not already running (`depends_on`). Compose **profiles** are not used: a profile would hide the simulator from default `docker compose up`.

The Compose service sets `UNS_mqtt__host=uns_mqtt_broker` and `UNS_simulation__duration=0` so the container publishes until you stop it. `duration: 0` means run until stopped; a positive value is minutes.

Build the image on its own (from `99_simulator/`, context is the repo root):

```bash
docker build -t uns/simulator:local --build-arg GIT_HASH=local -f ./Dockerfile ..
```

Quick start (local Python)

Use this only if you are iterating on the simulator code without Docker.

1. Install and prepare the development venv (the repository uses the uv wrapper like other modules):

   ```bash
   python -m pip install --upgrade pip uv
   uv venv
   uv sync
   ```

2. Configure the simulator
   - Copy [`../conf/.secrets_template.yaml`](../conf/.secrets_template.yaml) to `../conf/.secrets.yaml` and fill any secrets required.
   - Edit [`../conf/settings.yaml`](../conf/settings.yaml) to point to your MQTT broker and tune simulator options (the `simulator` environment).

3. Run locally
   - From the module folder (99_simulator) activate the venv and run:

   ```bash
   uv venv
   uv sync
   uv run uns_simulator
   ```

   - Point `mqtt.host` at `localhost` (the default) so the process can reach the Compose broker on host port 1883.
   - The module entrypoint is `uns_simulator.main:main`.

Core code pointers

- Entrypoint / CLI: `uns_simulator.main:main`
- Simulator implementation: `uns_simulator.simulator.Simulator`
- Device templates & helpers: `uns_simulator.devices`
- Config loader: `uns_simulator.config`
- Models: `uns_simulator.models`

Configuration notes

- MQTT settings are loaded from the repository-root `conf/settings.yaml` and secrets from `conf/.secrets.yaml` (based on the provided template).
- Typical keys:
  - mqtt.host (required)
  - mqtt.port (default 1883)
  - mqtt.transport ("tcp" or "websockets")
  - simulator.\* — device_count, publish_interval, device templates
  - simulation.duration — minutes to run; **0** means run until stopped (used by the Compose service)

Running tests

- Run unit tests (exclude integration tests):

  ```bash
  uv run pytest -m "not integrationtest" test/
  ```
