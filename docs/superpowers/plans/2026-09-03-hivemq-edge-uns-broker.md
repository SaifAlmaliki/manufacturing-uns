# HiveMQ Edge UNS Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Compose `emqx/emqx` with `hivemq/hivemq-edge` as `uns_mqtt_broker` so S7, EtherNet/IP, and OPC UA ingest through one OSS northbound path, and drop `opcua_client` from the running stack.

**Architecture:** Same Compose service name and MQTT port `1883`. Repo-owned `conf/hivemq/config.xml` (listener only by default) is mounted at `/opt/hivemq/conf/config.xml`. Plant adapters are authored in that XML, not in the Edge UI. `10_uns_opcua` stays in git but is not started. Kafka and GitHub Actions keep their current EMQX/Kafka setup.

**Tech Stack:** HiveMQ Edge (`hivemq/hivemq-edge:latest`), Docker Compose, pytest + PyYAML + `xml.etree` in `00_uns_config`.

**Spec:** `docs/superpowers/specs/2026-09-03-hivemq-edge-uns-broker-design.md`

## Global Constraints

- **OSS only.** Checked-in XML uses northbound S7 (`s7`), EtherNet/IP (`eip`), and OPC UA (`opcua`) only. No southbound mappings. No HiveMQ Kafka extension.
- **Service name stays `uns_mqtt_broker`.** Clients keep `UNS_mqtt__host: uns_mqtt_broker` and port `1883`.
- **Default config has no PLC targets.** The stack must become healthy with no plant.
- **Git is the tag map.** Edit `conf/hivemq/`, recreate the broker. Do not treat the Edge UI as source of truth.
- **Host `1883` stays MQTT TCP.** Edge console is `18080:8080`. Host `8080` is no longer MQTT-WS. Do not publish Keycloak on `8080`.
- **Do not change GitHub Actions MQTT images.** Mapper/GraphQL workflows keep `emqx/emqx`.
- **Do not delete `10_uns_opcua/`.** Do not rewrite `02_mqtt-cluster` helm/EMQX guides.
- **Do not add a root `.env`.** Secrets stay in `conf/.secrets.yaml`.
- **No live broker in pytest.** Contract tests read files. Compose smoke is Task 4, manual.
- **Historian contract.** Adapter publishes must carry `timestamp` (epoch ms) and `value`. Northbound mappings set `includeTimestamp` and QoS 1. No fabricated `status`.

---

## File Structure

```
conf/hivemq/config.xml                         # Compose default: MQTT 1883, no adapters
conf/hivemq/fixtures/adapters-unroutable.xml   # S7 + EIP + OPC UA at 192.0.2.1 (parse + optional start)
conf/hivemq/README.md                          # how to add a northbound tag
00_uns_config/test/test_hivemq_edge_stack.py   # file-contract tests (compose, prometheus, XML)
docker-compose.yml                             # image, ports, volume, drop opcua_client
docker-compose.dev.yml                         # drop opcua_client from prometheus depends_on
08_uns_observability/prometheus/prometheus.yml # drop uns_opcua scrape
README.md                                      # container table + image list + ports
```

---

### Task 1: Repo-owned Edge config

**Files:**
- Create: `conf/hivemq/config.xml`
- Create: `conf/hivemq/fixtures/adapters-unroutable.xml`
- Create: `conf/hivemq/README.md`
- Create: `00_uns_config/test/test_hivemq_edge_stack.py`

**Interfaces:**
- Consumes: nothing
- Produces: `HIVEMQ_CONFIG` path `conf/hivemq/config.xml`; fixture path `conf/hivemq/fixtures/adapters-unroutable.xml`; pytest module that later tasks extend

- [ ] **Step 1: Write the failing tests**

Create `00_uns_config/test/test_hivemq_edge_stack.py`:

```python
"""File contracts for HiveMQ Edge as uns_mqtt_broker.

Spec: docs/superpowers/specs/2026-09-03-hivemq-edge-uns-broker-design.md
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HIVEMQ_CONFIG = _REPO_ROOT / "conf" / "hivemq" / "config.xml"
_HIVEMQ_FIXTURE = _REPO_ROOT / "conf" / "hivemq" / "fixtures" / "adapters-unroutable.xml"
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_DEV_COMPOSE_FILE = _REPO_ROOT / "docker-compose.dev.yml"
_PROMETHEUS_FILE = (
    _REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
)


def _xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def test_default_config_exists_and_is_valid_xml():
    root = _xml(_HIVEMQ_CONFIG)
    assert root.tag.endswith("hivemq")


def test_default_config_listens_on_1883():
    ports = [el.text for el in _xml(_HIVEMQ_CONFIG).iter() if el.tag.endswith("port")]
    assert "1883" in ports


def test_default_config_has_no_protocol_adapters():
    root = _xml(_HIVEMQ_CONFIG)
    adapters = [el for el in root.iter() if el.tag.endswith("protocol-adapter")]
    assert adapters == []


def test_default_config_has_no_southbound_mappings():
    root = _xml(_HIVEMQ_CONFIG)
    south = [el for el in root.iter() if el.tag.endswith("southboundMapping")]
    assert south == []


def test_fixture_declares_s7_eip_and_opcua_at_documentation_hosts():
    root = _xml(_HIVEMQ_FIXTURE)
    adapters = [el for el in root.iter() if el.tag.endswith("protocol-adapter")]
    ids = {el.find("protocolId").text for el in adapters}
    assert ids == {"s7", "eip", "opcua"}
    for adapter in adapters:
        config = adapter.find("config")
        host = config.find("host")
        uri = config.find("uri")
        target = (host.text if host is not None else "") + (
            uri.text if uri is not None else ""
        )
        assert "192.0.2.1" in target
        for mapping in adapter.iter():
            if not mapping.tag.endswith("northboundMapping"):
                continue
            assert mapping.find("includeTimestamp").text == "true"
            assert mapping.find("maxQos").text == "1"
    assert [el for el in root.iter() if el.tag.endswith("southboundMapping")] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py -v`

Expected: FAIL with `FileNotFoundError` or "conf/hivemq/config.xml"

- [ ] **Step 3: Write the default config, fixture, and README**

`conf/hivemq/config.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<hivemq xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <mqtt-listeners>
        <tcp-listener>
            <port>1883</port>
            <bind-address>0.0.0.0</bind-address>
        </tcp-listener>
    </mqtt-listeners>
</hivemq>
```

`conf/hivemq/fixtures/adapters-unroutable.xml` (TEST-NET-1 `192.0.2.1` is never routed):

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<hivemq xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <mqtt-listeners>
        <tcp-listener>
            <port>1883</port>
            <bind-address>0.0.0.0</bind-address>
        </tcp-listener>
    </mqtt-listeners>
    <protocol-adapters>
        <protocol-adapter>
            <adapterId>fixture-s7</adapterId>
            <protocolId>s7</protocolId>
            <config>
                <host>192.0.2.1</host>
                <port>102</port>
                <controllerType>S7_1500</controllerType>
            </config>
            <northboundMappings>
                <northboundMapping>
                    <topic>Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed</topic>
                    <tagName>fixture_s7_speed</tagName>
                    <maxQos>1</maxQos>
                    <includeTimestamp>true</includeTimestamp>
                </northboundMapping>
            </northboundMappings>
            <tags>
                <tag>
                    <name>fixture_s7_speed</name>
                    <description>Unroutable S7 parse fixture</description>
                    <definition>
                        <tagAddress>%ID103</tagAddress>
                        <dataType>DINT</dataType>
                    </definition>
                </tag>
            </tags>
        </protocol-adapter>
        <protocol-adapter>
            <adapterId>fixture-eip</adapterId>
            <protocolId>eip</protocolId>
            <config>
                <host>192.0.2.1</host>
                <port>44818</port>
            </config>
            <northboundMappings>
                <northboundMapping>
                    <topic>Acme/Test/Area/Line/Cell/EIP/ProcessValue/Count</topic>
                    <tagName>fixture_eip_count</tagName>
                    <maxQos>1</maxQos>
                    <includeTimestamp>true</includeTimestamp>
                </northboundMapping>
            </northboundMappings>
            <tags>
                <tag>
                    <name>fixture_eip_count</name>
                    <description>Unroutable EtherNet/IP parse fixture</description>
                    <definition>
                        <address>Program:MainProgram.Count</address>
                        <dataType>DINT</dataType>
                    </definition>
                </tag>
            </tags>
        </protocol-adapter>
        <protocol-adapter>
            <adapterId>fixture-opcua</adapterId>
            <protocolId>opcua</protocolId>
            <config>
                <uri>opc.tcp://192.0.2.1:4840</uri>
                <opcuaToMqtt/>
            </config>
            <northboundMappings>
                <northboundMapping>
                    <topic>Acme/Test/Area/Line/Cell/OPCUA/ProcessValue/Temperature</topic>
                    <tagName>fixture_opcua_temp</tagName>
                    <maxQos>1</maxQos>
                    <includeTimestamp>true</includeTimestamp>
                </northboundMapping>
            </northboundMappings>
            <southboundMappings/>
            <tags>
                <tag>
                    <name>fixture_opcua_temp</name>
                    <description>Unroutable OPC UA parse fixture</description>
                    <definition>
                        <node>ns=1;i=1004</node>
                    </definition>
                </tag>
            </tags>
        </protocol-adapter>
    </protocol-adapters>
</hivemq>
```

`conf/hivemq/README.md`:

```markdown
# HiveMQ Edge config

`config.xml` is mounted into `uns_mqtt_broker` at `/opt/hivemq/conf/config.xml`.

Default file: MQTT TCP on `1883`, no protocol adapters. The stack starts with no PLC.

To ingest S7, EtherNet/IP, or OPC UA, copy a `<protocol-adapter>` from
`fixtures/adapters-unroutable.xml`, point `host` / `uri` at the real device, set
`topic` to the ISA-95 path, keep `includeTimestamp` true and `maxQos` 1, and
recreate the broker:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
```

Do not add `<southboundMapping>` entries. The Edge console on host port `18080`
(default login `admin` / `hivemq`) is for inspection; git remains the source of
truth. Mitsubishi is out of scope.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py -v`

Expected: the four default-config tests and the fixture test PASS. Compose tests are not in this file yet.

- [ ] **Step 5: Commit**

```bash
git add conf/hivemq/config.xml conf/hivemq/fixtures/adapters-unroutable.xml conf/hivemq/README.md 00_uns_config/test/test_hivemq_edge_stack.py
git commit -m "test(hivemq): add Edge config and XML contract tests"
```

---

### Task 2: Swap `uns_mqtt_broker` to HiveMQ Edge

**Files:**
- Modify: `docker-compose.yml:28-42` (`uns_mqtt_broker` service)
- Modify: `00_uns_config/test/test_hivemq_edge_stack.py` (add compose assertions)

**Interfaces:**
- Consumes: `conf/hivemq/config.xml` from Task 1
- Produces: Compose service `uns_mqtt_broker` image `hivemq/hivemq-edge:latest`, ports `1883:1883` and `18080:8080`, volume `./conf/hivemq/config.xml:/opt/hivemq/conf/config.xml:ro`

- [ ] **Step 1: Append failing compose tests**

Add to `00_uns_config/test/test_hivemq_edge_stack.py`:

```python
def _compose() -> dict:
    return yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))


def test_broker_image_is_hivemq_edge():
    assert _compose()["services"]["uns_mqtt_broker"]["image"] == "hivemq/hivemq-edge:latest"


def test_broker_publishes_mqtt_1883_and_console_18080():
    ports = _compose()["services"]["uns_mqtt_broker"]["ports"]
    assert "1883:1883" in ports
    assert "18080:8080" in ports
    assert "8080:8080" not in ports
    assert "1884:1884" not in ports
    assert "8090:8090" not in ports


def test_broker_mounts_repo_config_read_only():
    volumes = _compose()["services"]["uns_mqtt_broker"]["volumes"]
    assert "./conf/hivemq/config.xml:/opt/hivemq/conf/config.xml:ro" in volumes


def test_broker_healthcheck_does_not_call_emqx():
    check = _compose()["services"]["uns_mqtt_broker"]["healthcheck"]["test"]
    joined = " ".join(check)
    assert "emqx" not in joined
    assert "1883" in joined
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py::test_broker_image_is_hivemq_edge ./00_uns_config/test/test_hivemq_edge_stack.py::test_broker_publishes_mqtt_1883_and_console_18080 ./00_uns_config/test/test_hivemq_edge_stack.py::test_broker_mounts_repo_config_read_only ./00_uns_config/test/test_hivemq_edge_stack.py::test_broker_healthcheck_does_not_call_emqx -v`

Expected: FAIL — image is still `emqx/emqx:latest`

- [ ] **Step 3: Replace the `uns_mqtt_broker` service**

In `docker-compose.yml`, replace the whole `uns_mqtt_broker` block (lines 28–42) with:

```yaml
  uns_mqtt_broker:
    image: "hivemq/hivemq-edge:latest"
    ports:
      - "1883:1883" # MQTT, unencrypted, unauthenticated
      - "18080:8080" # HiveMQ Edge console / API. Not MQTT-WS.
    volumes:
      - ./conf/hivemq/config.xml:/opt/hivemq/conf/config.xml:ro
    # Healthy = MQTT TCP is accepting connections, not "every PLC is up".
    # /dev/tcp is bash; the official image is Debian-based.
    healthcheck:
      test: ["CMD-SHELL", "timeout 2 bash -c 'echo > /dev/tcp/127.0.0.1/1883' || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 90s
```

Leave every `depends_on: uns_mqtt_broker` / `UNS_mqtt__host` unchanged.

- [ ] **Step 4: Run the compose contract tests**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py -v`

Expected: all Task 1 and Task 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml 00_uns_config/test/test_hivemq_edge_stack.py
git commit -m "feat(compose): run HiveMQ Edge as uns_mqtt_broker"
```

---

### Task 3: Remove `opcua_client` from the running stack

**Files:**
- Modify: `docker-compose.yml` (`opcua_client` service ~205–231, `uns_prometheus` `depends_on` ~419–424, `volumes: opcua_spool` ~487–488)
- Modify: `docker-compose.dev.yml:17-22`
- Modify: `08_uns_observability/prometheus/prometheus.yml:18-20`
- Modify: `README.md` (container table, Docker images, typical flow)
- Modify: `docs/superpowers/specs/2026-09-03-hivemq-edge-uns-broker-design.md` (Status line)
- Modify: `00_uns_config/test/test_hivemq_edge_stack.py`

**Interfaces:**
- Consumes: Task 2 broker service
- Produces: no `opcua_client` service; no `opcua_spool` volume; no Prometheus job `uns_opcua`; README describes Edge ingest

- [ ] **Step 1: Append failing removal tests**

Add to `00_uns_config/test/test_hivemq_edge_stack.py`:

```python
def _dev_compose() -> dict:
    return yaml.safe_load(_DEV_COMPOSE_FILE.read_text(encoding="utf-8"))


def _prometheus() -> dict:
    return yaml.safe_load(_PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_opcua_client_is_not_a_compose_service():
    assert "opcua_client" not in _compose()["services"]
    assert "opcua_spool" not in (_compose().get("volumes") or {})


def test_prometheus_does_not_scrape_opcua_client():
    jobs = {job["job_name"]: job for job in _prometheus()["scrape_configs"]}
    assert "uns_opcua" not in jobs
    targets = [
        t
        for job in _prometheus()["scrape_configs"]
        for t in job["static_configs"][0]["targets"]
    ]
    assert "opcua_client:9093" not in targets


def test_prometheus_compose_does_not_depend_on_opcua_client():
    assert "opcua_client" not in _compose()["services"]["uns_prometheus"]["depends_on"]
    assert "opcua_client" not in _dev_compose()["services"]["uns_prometheus"]["depends_on"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py::test_opcua_client_is_not_a_compose_service ./00_uns_config/test/test_hivemq_edge_stack.py::test_prometheus_does_not_scrape_opcua_client ./00_uns_config/test/test_hivemq_edge_stack.py::test_prometheus_compose_does_not_depend_on_opcua_client -v`

Expected: FAIL — `opcua_client` is still a service

- [ ] **Step 3: Delete the service, volume, scrape, and docs**

1. Delete the entire `opcua_client` service block in `docker-compose.yml` (the comment immediately above it, from "Read-only OPC UA edge connector" through its `depends_on`).
2. In `uns_prometheus.depends_on`, remove the `- opcua_client` line. Leave `historian_client`, `graphdb_client`, `uns_simulator`, `oee_client`.
3. Delete the `volumes:` `opcua_spool:` entry at the bottom of `docker-compose.yml`. If `volumes:` becomes empty, delete the `volumes:` key too.
4. In `docker-compose.dev.yml`, replace the prometheus `depends_on` with:

```yaml
  uns_prometheus:
    depends_on: !reset
      - historian_client
      - graphdb_client
      - oee_client
```

(`uns_simulator` is already omitted here because `npm run stack` scales it to 0.)

5. In `08_uns_observability/prometheus/prometheus.yml`, delete the `uns_opcua` job (the four lines that target `opcua_client:9093`). Keep `uns_simulator` on `9093`.

6. In `README.md` **What each container does**, replace the `uns_mqtt_broker` row and delete the `opcua_client` row:

```markdown
| `uns_mqtt_broker` | MQTT backbone (HiveMQ Edge). Devices, the simulator, mapper clients, and Edge protocol adapters (S7, EtherNet/IP, OPC UA) publish/subscribe here. Host ports: `1883` (MQTT), `18080` (Edge console). |
```

7. In `README.md` **Docker images**, replace the EMQX bullet and delete the built `opcua_client` bullet:

```markdown
- `hivemq/hivemq-edge:latest` — MQTT broker plus northbound S7, EtherNet/IP, and OPC UA adapters.
```

8. In `README.md` typical flow, keep the sentence but it now includes Edge adapters as plant devices. No new diagram required.

9. In the spec header, change `Status: Draft — awaiting review` to `Status: Approved`.

Do not delete `10_uns_opcua/` or `conf/settings.yaml` `opcua:` keys.

- [ ] **Step 4: Run contract tests**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py ./12_uns_oee/test/test_deployment.py -v`

Expected: PASS. `test_deployment.py` still unique-targets Prometheus jobs; removing `uns_opcua` must not break uniqueness.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml 08_uns_observability/prometheus/prometheus.yml README.md docs/superpowers/specs/2026-09-03-hivemq-edge-uns-broker-design.md 00_uns_config/test/test_hivemq_edge_stack.py
git commit -m "feat(compose): ingest S7/EIP/OPC UA via Edge; drop opcua_client"
```

---

### Task 4: Compose smoke and publisher identity

**Files:**
- None to edit unless healthcheck or mount path is wrong (fix in this task, do not skip)

**Interfaces:**
- Consumes: Tasks 1–3
- Produces: verified running stack; written note in the commit message if the Edge MQTT client id was observed

- [ ] **Step 1: Recreate the broker (and only what depends on its health)**

From the repository root, with `conf/.secrets.yaml` already present:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
uv run uns_compose ps uns_mqtt_broker
```

Expected: `uns_mqtt_broker` state running, health `healthy` within ~90s.

If health stays `starting` because `/dev/tcp` is missing, replace the healthcheck with:

```yaml
    healthcheck:
      test: ["CMD", "java", "-version"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 90s
```

That is a last resort (process up, not listener up). Prefer, if the image has it:

```yaml
    healthcheck:
      test: ["CMD", "test", "-f", "/opt/hivemq/data/.ready"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 90s
```

Then update `test_broker_healthcheck_does_not_call_emqx` so `joined` still contains no `emqx` and still mentions `1883` **or** `.ready`. If you switch to `.ready`, change the assertion to `assert "emqx" not in joined` and `assert ".ready" in joined`. Re-run `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py -v` and commit that fix before continuing.

- [ ] **Step 2: MQTT 5 on host 1883**

```bash
uv run python -c "import paho.mqtt.client as m,time; c=m.Client(m.CallbackAPIVersion.VERSION2, client_id='hivemq-smoke', protocol=m.MQTTv5); got={'n':0}; c.on_message=lambda *a: got.__setitem__('n',1); c.connect('localhost',1883,60); c.subscribe('Acme/hivemq/smoke',1); c.loop_start(); time.sleep(0.5); c.publish('Acme/hivemq/smoke', b'{\"timestamp\":1,\"value\":1}',1); time.sleep(1); c.loop_stop(); c.disconnect(); assert got['n']==1, got"
```

Expected: no exception. If `paho` is missing: `uv run python -c "import uns_mqtt"` is fine — use whatever MQTT client this repo already imports (`paho` is pulled by `02_mqtt-cluster`).

- [ ] **Step 3: Edge console on 18080; 8080 is not MQTT-WS**

```bash
curl -s -o NUL -w "%{http_code}" http://localhost:18080/
```

Expected: `200` or `302` (console login). Default credentials `admin` / `hivemq` if you open it in a browser.

```bash
curl -s -o NUL -w "%{http_code}" http://localhost:8080/
```

Expected: connection refused **or** Keycloak is still unpublished so this is not a second issuer. It must not be EMQX MQTT-WS. (`uns_keycloak` 8080 stays unpublished; this curl talks to the host.)

- [ ] **Step 4: `opcua_client` is gone; `:9093` is unpublished**

```bash
uv run uns_compose ps -a
```

Expected: no `opcua_client` row.

```bash
curl -s -o NUL -w "%{http_code}" http://localhost:9093/metrics
```

Expected: connection refused.

- [ ] **Step 5: Optional — fixture config still yields a healthy broker**

```bash
uv run uns_compose stop uns_mqtt_broker
```

Temporarily point the volume at the fixture **only for this check** (do not commit):

```bash
docker run --rm -d --name edge-fixture -p 1884:1883 -p 18081:8080 -v "%CD%/conf/hivemq/fixtures/adapters-unroutable.xml:/opt/hivemq/conf/config.xml:ro" hivemq/hivemq-edge:latest
```

On Unix replace `%CD%` with `$(pwd)`. Wait ~60s, then:

```bash
uv run python -c "import paho.mqtt.client as m; c=m.Client(m.CallbackAPIVersion.VERSION2, protocol=m.MQTTv5); c.connect('localhost',1884,60); c.disconnect(); print('ok')"
docker logs edge-fixture --tail 40
docker stop edge-fixture
```

Expected: MQTT connect succeeds. Logs may show adapter connection errors to `192.0.2.1`; that is success. The process must not exit.

- [ ] **Step 6: Publisher client id stability**

Bring the stack broker back (`uv run uns_compose up -d uns_mqtt_broker`). In the Edge console (http://localhost:18080) or logs, find the client id used when an adapter publishes (none will publish with the default config).

With the default config there are no adapter publishes. Record that fact in the commit message: identity check is deferred until a real adapter is configured. **If** you ran Step 5 and adapters attempted to publish, grep logs for the MQTT client id, recreate the fixture container, and confirm the same id. If it changes across recreate, **stop** — do not ship; file the finding against the spec section 5 payload contract.

- [ ] **Step 7: Simulator still reaches the new broker**

If the rest of the stack is already up:

```bash
uv run uns_compose up -d
uv run uns_compose logs --tail 20 uns_simulator graphdb_client historian_client
```

Expected: MQTT connected / publishing, no flood of connection refused to `uns_mqtt_broker:1883`.

If you only started the broker, start at least the simulator:

```bash
uv run uns_compose up -d uns_simulator
```

- [ ] **Step 8: Commit only if Step 1 required a healthcheck fix**

If compose or tests changed:

```bash
git add docker-compose.yml 00_uns_config/test/test_hivemq_edge_stack.py
git commit -m "fix(compose): correct HiveMQ Edge healthcheck"
```

If nothing changed, do not create an empty commit.

---

## Self-review (plan vs spec)

| Spec section | Task |
| --- | --- |
| Replace EMQX, keep service name, `1883` | Task 2 |
| `conf/hivemq/config.xml`, no default adapters | Task 1 |
| Fixture S7 + EIP + OPC UA, unroutable, parse/start | Task 1, Task 4 Step 5 |
| Payload `timestamp` + `value`, QoS 1, `includeTimestamp` | Task 1 fixture + README |
| Console `18080`, drop MQTT-WS `8080`, drop `1884`/`8090` | Task 2, Task 4 |
| Health = MQTT up, empty plant OK | Task 2 healthcheck, Task 4 |
| Remove `opcua_client`, spool, `:9093`, Prometheus job | Task 3 |
| README + image list | Task 3 |
| CI keeps EMQX | Global constraint; no workflow files in this plan |
| Kafka unchanged | No kafka file touches |
| No southbound / Mitsubishi / delete `10_uns_opcua` / helm | Global constraints |
| Client id stable | Task 4 Step 6; halt if unstable |
| Compose smoke, port contract, removal check | Task 4 |
