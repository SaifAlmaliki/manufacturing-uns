# Site and Enterprise Compose Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a laptop mesh of three full Site Instances (HiveMQ Edge) MQTT-bridged to one Enterprise Instance (HiveMQ CE + Kafka) without a second codebase or a second console.

**Architecture:** `docker-compose.yml` stays the single-Instance path. New `docker-compose.site.yml` is started three times (`site1`–`site3`); `docker-compose.enterprise.yml` is the twin. Each site Edge XML bridges `#` to network alias `enterprise_mqtt`. Same `11_frontend` and GraphQL; enterprise on port `8388` shows all three plants because those topics arrived on CE.

**Tech Stack:** Docker Compose, HiveMQ Edge, HiveMQ CE (`hivemq/hivemq-ce`), Dynaconf, pytest + PyYAML + `xml.etree` in `00_uns_config`.

**Spec:** `docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md`

## Global Constraints

- **Same repository.** No `13_enterprise`, no second frontend. Enterprise-specific UI is a later spec.
- **OSS only.** No HiveMQ Kafka extension. No `<persist>true</persist>` on the Edge bridge — offline buffering is commercial. Live forward only; the site historian still has local Historic Events if CE is down.
- **`docker-compose.yml` unchanged in behaviour.** `npm run stack` stays the single-Instance path.
- **No Kafka on a site.** Kafka + kafka mapper exist only on enterprise.
- **No simulator, Sparkplug mapper, or PLC adapters on enterprise.**
- **Grafana stays unpublished on 3000.** Open `/grafana` on that Instance's console port.
- **Keycloak stays unpublished.** `KC_HOSTNAME` is `http://localhost:<console>/auth`.
- **CE has no Edge Control Center.** Enterprise MQTT host port is `1893` only. Do not invent `18093`.
- **Bridge host is `enterprise_mqtt`.** Filter `#`. Destination `{#}` (same topic names).
- **Do not start the four-stack mesh in CI.** File-contract tests only. Mapper workflows keep `emqx/emqx`.
- **Do not add a root `.env`.** Secrets stay in `conf/.secrets.yaml`. Port offsets live in `conf/instances/*/compose.env`.
- **No AWS / Azure / Databricks clients** in this plan.

---

## File Structure

```
00_uns_config/test/test_site_enterprise_mesh.py   # file contracts
00_uns_config/src/uns_config/compose_env.py       # --instance
00_uns_config/test/test_compose_env.py            # --instance argv
conf/hivemq/site1.xml                             # Edge + bridge
conf/hivemq/site2.xml
conf/hivemq/site3.xml
conf/hivemq/enterprise.xml                        # CE listeners only
conf/hivemq/README.md                             # site vs enterprise XML
conf/instances/site1/compose.env
conf/instances/site2/compose.env
conf/instances/site2/simulator/plant.yaml         # Site2 only
conf/instances/site3/compose.env
conf/instances/site3/simulator/plant.yaml         # Site3 only
conf/instances/enterprise/compose.env
docker-compose.site.yml
docker-compose.enterprise.yml
11_frontend/nginx.conf                            # optional simulator upstream
README.md
docs/adr/0010-site-instance-and-enterprise-cloud-hop.md
docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md
```

`conf/simulator/plant.yaml` stays Site1 and is what `site1` and `npm run stack` use.

---

### Task 1: Mesh file-contract tests

**Files:**
- Create: `00_uns_config/test/test_site_enterprise_mesh.py`

**Interfaces:**
- Consumes: spec port table and service lists
- Produces: pytest module later tasks make green

- [ ] **Step 1: Write the failing tests**

Create `00_uns_config/test/test_site_enterprise_mesh.py`:

```python
"""File contracts for site / enterprise Compose profiles.

Spec: docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HIVEMQ = _REPO_ROOT / "conf" / "hivemq"
_INSTANCES = _REPO_ROOT / "conf" / "instances"
_SITE_COMPOSE = _REPO_ROOT / "docker-compose.site.yml"
_ENTERPRISE_COMPOSE = _REPO_ROOT / "docker-compose.enterprise.yml"

_SITE_SERVICES = {
    "uns_mqtt_broker",
    "uns_timescale_db",
    "tsdb_setup_script",
    "asset_model_setup",
    "uns_neo4j_db",
    "graphdb_client",
    "historian_client",
    "spb_mapper_client",
    "uns_simulator",
    "oee_client",
    "graphql_server",
    "uns_keycloak",
    "uns_frontend",
    "uns_grafana",
    "uns_prometheus",
}

_ENTERPRISE_SERVICES = (
    _SITE_SERVICES
    - {"uns_simulator", "spb_mapper_client"}
    | {"uns_kafka_broker", "kafka_mapper_client"}
)


def _xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _env_file(name: str) -> dict[str, str]:
    text = (_INSTANCES / name / "compose.env").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def test_site_xml_files_bridge_hash_to_enterprise_mqtt():
    for name in ("site1", "site2", "site3"):
        root = _xml(_HIVEMQ / f"{name}.xml")
        hosts = [el.text for el in root.iter() if el.tag.endswith("host")]
        filters = [el.text for el in root.iter() if el.tag.endswith("mqtt-topic-filter")]
        destinations = [el.text for el in root.iter() if el.tag.endswith("destination")]
        persist = [el.text for el in root.iter() if el.tag.endswith("persist")]
        south = [el for el in root.iter() if el.tag.endswith("southboundMapping")]
        assert "enterprise_mqtt" in hosts, name
        assert "#" in filters, name
        assert "{#}" in destinations, name
        assert "true" not in persist, "OSS Edge: do not enable commercial persist"
        assert south == [], name


def test_enterprise_xml_has_no_protocol_adapters_or_bridges():
    root = _xml(_HIVEMQ / "enterprise.xml")
    assert [el for el in root.iter() if el.tag.endswith("protocol-adapter")] == []
    assert [el for el in root.iter() if el.tag.endswith("mqtt-bridge")] == []
    assert [el for el in root.iter() if el.tag.endswith("southboundMapping")] == []


def test_site_compose_has_plant_services_and_no_kafka():
    services = _compose(_SITE_COMPOSE)["services"]
    assert _SITE_SERVICES <= set(services)
    assert "uns_kafka_broker" not in services
    assert "kafka_mapper_client" not in services
    assert services["uns_mqtt_broker"]["image"] == "hivemq/hivemq-edge:latest"


def test_enterprise_compose_is_the_twin():
    services = _compose(_ENTERPRISE_COMPOSE)["services"]
    assert _ENTERPRISE_SERVICES <= set(services)
    assert "uns_simulator" not in services
    assert "spb_mapper_client" not in services
    assert services["uns_mqtt_broker"]["image"] == "hivemq/hivemq-ce:latest"
    kafka_ports = services["uns_kafka_broker"]["ports"]
    assert "9092:9092" in kafka_ports


def test_compose_env_port_table():
    assert _env_file("site1")["SITE_CONSOLE_PORT"] == "8088"
    assert _env_file("site1")["SITE_MQTT_PORT"] == "1883"
    assert _env_file("site1")["SITE_PROMETHEUS_PORT"] == "9090"
    assert _env_file("site2")["SITE_CONSOLE_PORT"] == "8188"
    assert _env_file("site2")["SITE_MQTT_PORT"] == "2883"
    assert _env_file("site2")["SITE_PROMETHEUS_PORT"] == "9190"
    assert _env_file("site3")["SITE_CONSOLE_PORT"] == "8288"
    assert _env_file("site3")["SITE_MQTT_PORT"] == "3883"
    assert _env_file("site3")["SITE_PROMETHEUS_PORT"] == "9290"
    ent = _env_file("enterprise")
    assert ent["SITE_CONSOLE_PORT"] == "8388"
    assert ent["SITE_MQTT_PORT"] == "1893"
    assert ent["SITE_PROMETHEUS_PORT"] == "9390"
    assert "18093" not in ent.values()


def test_site2_and_site3_plant_yaml_rename_the_site_only():
    for name in ("Site2", "Site3"):
        raw = yaml.safe_load(
            (_INSTANCES / name.lower() / "simulator" / "plant.yaml").read_text(
                encoding="utf-8"
            )
        )
        sites = [s["name"] for s in raw["sites"]]
        assert sites == [name]
        assert raw["profiles"]["wtp"]["sites"] == [name]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py -v`

Expected: FAIL with `FileNotFoundError` or missing compose files.

- [ ] **Step 3: Commit the failing tests**

```bash
git add 00_uns_config/test/test_site_enterprise_mesh.py
git commit -m "test(compose): add site and enterprise mesh file contracts"
```

---

### Task 2: HiveMQ site and enterprise XML

**Files:**
- Create: `conf/hivemq/site1.xml`
- Create: `conf/hivemq/site2.xml`
- Create: `conf/hivemq/site3.xml`
- Create: `conf/hivemq/enterprise.xml`

**Interfaces:**
- Consumes: Task 1 XML assertions (`enterprise_mqtt`, `#`, `{#}`, no persist, no southbound)
- Produces: four XML paths mounted by later compose files

- [ ] **Step 1: Write site XML**

`conf/hivemq/site1.xml`, `site2.xml`, and `site3.xml` are identical except `<id>` (`site1-to-ce` / `site2-to-ce` / `site3-to-ce`) and `<client-id>` (`site1-bridge` / `site2-bridge` / `site3-bridge`).

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<hivemq xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <mqtt-listeners>
        <tcp-listener>
            <port>1883</port>
            <bind-address>0.0.0.0</bind-address>
        </tcp-listener>
    </mqtt-listeners>
    <admin-api>
        <enabled>true</enabled>
        <listeners>
            <http-listener>
                <port>8080</port>
                <bind-address>0.0.0.0</bind-address>
            </http-listener>
        </listeners>
    </admin-api>
    <mqtt-bridges>
        <mqtt-bridge>
            <id>site1-to-ce</id>
            <remote-broker>
                <host>enterprise_mqtt</host>
                <port>1883</port>
                <mqtt>
                    <client-id>site1-bridge</client-id>
                </mqtt>
            </remote-broker>
            <forwarded-topics>
                <forwarded-topic>
                    <filters>
                        <mqtt-topic-filter>#</mqtt-topic-filter>
                    </filters>
                    <destination>{#}</destination>
                    <max-qos>1</max-qos>
                </forwarded-topic>
            </forwarded-topics>
        </mqtt-bridge>
    </mqtt-bridges>
</hivemq>
```

Do not copy the simulation `<protocol-adapters>` block from `config.xml`. Site mesh XML is listener + bridge only. Single-Instance `config.xml` is unchanged.

- [ ] **Step 2: Write enterprise CE XML**

`conf/hivemq/enterprise.xml` (HiveMQ CE uses `<listeners>`, not Edge `<mqtt-listeners>`):

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<hivemq>
    <listeners>
        <tcp-listener>
            <port>1883</port>
            <bind-address>0.0.0.0</bind-address>
        </tcp-listener>
    </listeners>
</hivemq>
```

- [ ] **Step 3: Re-run the XML tests**

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py::test_site_xml_files_bridge_hash_to_enterprise_mqtt ./00_uns_config/test/test_site_enterprise_mesh.py::test_enterprise_xml_has_no_protocol_adapters_or_bridges -v`

Expected: PASS. Other tests in the module still FAIL.

- [ ] **Step 4: Commit**

```bash
git add conf/hivemq/site1.xml conf/hivemq/site2.xml conf/hivemq/site3.xml conf/hivemq/enterprise.xml
git commit -m "feat(hivemq): add site MQTT bridges and CE listener XML"
```

---

### Task 3: Per-Instance compose.env and plant overlays

**Files:**
- Create: `conf/instances/site1/compose.env`
- Create: `conf/instances/site2/compose.env`
- Create: `conf/instances/site2/simulator/plant.yaml`
- Create: `conf/instances/site3/compose.env`
- Create: `conf/instances/site3/simulator/plant.yaml`
- Create: `conf/instances/enterprise/compose.env`

**Interfaces:**
- Consumes: spec port table
- Produces: env keys `SITE_MQTT_PORT`, `SITE_EDGE_CONSOLE_PORT`, `SITE_CONSOLE_PORT`, `SITE_GRAPHQL_PORT`, `SITE_PROMETHEUS_PORT`, `SITE_TIMESCALE_PORT`, `SITE_NEO4J_BROWSER_PORT`, `SITE_NEO4J_BOLT_PORT`, `HIVEMQ_CONFIG`, `CONSOLE_ORIGIN`

- [ ] **Step 1: Write compose.env files**

`conf/instances/site1/compose.env`:

```
SITE_MQTT_PORT=1883
SITE_EDGE_CONSOLE_PORT=18080
SITE_CONSOLE_PORT=8088
SITE_GRAPHQL_PORT=8000
SITE_PROMETHEUS_PORT=9090
SITE_TIMESCALE_PORT=5432
SITE_NEO4J_BROWSER_PORT=7474
SITE_NEO4J_BOLT_PORT=7687
HIVEMQ_CONFIG=./conf/hivemq/site1.xml
CONSOLE_ORIGIN=http://localhost:8088
```

`conf/instances/site2/compose.env` — same keys with `2883`, `18081`, `8188`, `8100`, `9190`, `5532`, `7574`, `7787`, `./conf/hivemq/site2.xml`, `http://localhost:8188`.

`conf/instances/site3/compose.env` — `3883`, `18082`, `8288`, `8200`, `9290`, `5632`, `7674`, `7887`, `./conf/hivemq/site3.xml`, `http://localhost:8288`.

`conf/instances/enterprise/compose.env`:

```
SITE_MQTT_PORT=1893
SITE_CONSOLE_PORT=8388
SITE_GRAPHQL_PORT=8300
SITE_PROMETHEUS_PORT=9390
SITE_TIMESCALE_PORT=5732
SITE_NEO4J_BROWSER_PORT=7774
SITE_NEO4J_BOLT_PORT=7987
HIVEMQ_CONFIG=./conf/hivemq/enterprise.xml
CONSOLE_ORIGIN=http://localhost:8388
```

No `SITE_EDGE_CONSOLE_PORT` on enterprise.

- [ ] **Step 2: Write Site2 and Site3 plant.yaml**

Copy `conf/simulator/plant.yaml` to `conf/instances/site2/simulator/plant.yaml` and `conf/instances/site3/simulator/plant.yaml`. Replace every `Site1` with `Site2` or `Site3` respectively, including `profiles.wtp.sites`. Leave equipment cells unchanged.

- [ ] **Step 3: Re-run env and plant tests**

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py::test_compose_env_port_table ./00_uns_config/test/test_site_enterprise_mesh.py::test_site2_and_site3_plant_yaml_rename_the_site_only -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add conf/instances
git commit -m "feat(conf): add site and enterprise instance port overlays"
```

---

### Task 4: Site compose file

**Files:**
- Create: `docker-compose.site.yml`

**Interfaces:**
- Consumes: `HIVEMQ_CONFIG`, `SITE_*_PORT`, `CONSOLE_ORIGIN` from compose.env; Task 2 XML
- Produces: plant stack with external network `uns_enterprise`, no Kafka

- [ ] **Step 1: Copy `docker-compose.yml` to `docker-compose.site.yml` and apply these edits**

1. Delete services `uns_kafka_broker` and `kafka_mapper_client`.
2. From `graphql_server`: delete `UNS_kafka__config` and `depends_on.uns_kafka_broker`.
3. Do not publish historian `9091` (Prometheus scrapes inside the network; three sites would collide).
4. Replace these port and hostname lines:

`uns_mqtt_broker`:

```yaml
    image: "hivemq/hivemq-edge:latest"
    ports:
      - "${SITE_MQTT_PORT:-1883}:1883"
      - "${SITE_EDGE_CONSOLE_PORT:-18080}:8080"
    volumes:
      - ${HIVEMQ_CONFIG:-./conf/hivemq/site1.xml}:/opt/hivemq/conf/config.xml:ro
```

`uns_timescale_db` ports: `"${SITE_TIMESCALE_PORT:-5432}:5432"`

`uns_neo4j_db` ports: `"${SITE_NEO4J_BROWSER_PORT:-7474}:7474"` and `"${SITE_NEO4J_BOLT_PORT:-7687}:7687"`

`graphql_server` ports: `"${SITE_GRAPHQL_PORT:-8000}:8000"`

`uns_frontend` ports: `"${SITE_CONSOLE_PORT:-8088}:80"`

`uns_prometheus` ports: `"${SITE_PROMETHEUS_PORT:-9090}:9090"`

`uns_keycloak` environment: `KC_HOSTNAME: ${CONSOLE_ORIGIN:-http://localhost:8088}/auth`

`uns_grafana` environment:

```yaml
      GF_AUTH_GENERIC_OAUTH_AUTH_URL: "${CONSOLE_ORIGIN:-http://localhost:8088}/auth/realms/uns/protocol/openid-connect/auth"
      GF_SERVER_ROOT_URL: "${CONSOLE_ORIGIN:-http://localhost:8088}/grafana/"
```

5. Add at the bottom (and do not set `container_name` on any service — project name prefixes them):

```yaml
networks:
  default:
    name: uns_enterprise
    external: true
```

6. Site2 and site3 simulator volume extra line on `uns_simulator` only when `HIVEMQ_CONFIG` is site2/site3 — **do not special-case in YAML**. Instead always add:

```yaml
    volumes:
      - ./conf:/app/conf
      - ${SITE_PLANT_YAML:-./conf/simulator/plant.yaml}:/app/conf/simulator/plant.yaml:ro
```

Add to site1 `compose.env`: `SITE_PLANT_YAML=./conf/simulator/plant.yaml`

Add to site2: `SITE_PLANT_YAML=./conf/instances/site2/simulator/plant.yaml`

Add to site3: `SITE_PLANT_YAML=./conf/instances/site3/simulator/plant.yaml`

7. Update `test_compose_env_port_table` is already green; `SITE_PLANT_YAML` is not asserted. Add the three `SITE_PLANT_YAML` lines to the env files in this task.

- [ ] **Step 2: Run site compose contracts**

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py::test_site_compose_has_plant_services_and_no_kafka -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.site.yml conf/instances/site1/compose.env conf/instances/site2/compose.env conf/instances/site3/compose.env
git commit -m "feat(compose): add parameterized site stack without Kafka"
```

---

### Task 5: Enterprise compose and optional simulator proxy

**Files:**
- Create: `docker-compose.enterprise.yml`
- Modify: `11_frontend/nginx.conf`

**Interfaces:**
- Consumes: site compose as the template; enterprise compose.env
- Produces: twin stack; nginx starts when `uns_simulator` DNS is missing

- [ ] **Step 1: Write the failing nginx behaviour into the mesh tests**

Append to `00_uns_config/test/test_site_enterprise_mesh.py`:

```python
def test_nginx_simulator_proxy_uses_a_variable_upstream():
    text = (_REPO_ROOT / "11_frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "resolver 127.0.0.11" in text
    assert "$simulator_upstream" in text
```

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py::test_nginx_simulator_proxy_uses_a_variable_upstream -v`

Expected: FAIL — `resolver` not in nginx.conf.

- [ ] **Step 2: Change `11_frontend/nginx.conf` `location /simulator`**

Replace the `proxy_pass http://uns_simulator:8099;` block with:

```nginx
    location /simulator {
        resolver 127.0.0.11 valid=10s ipv6=off;
        set $simulator_upstream uns_simulator;
        proxy_pass http://$simulator_upstream:8099;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 7d;
        proxy_send_timeout 7d;
    }
```

Keep any headers already present in that location; only the `resolver` / `$simulator_upstream` / `proxy_pass` lines are required. Site stacks still resolve `uns_simulator`. Enterprise `/simulator` returns 502. That is correct.

- [ ] **Step 3: Create `docker-compose.enterprise.yml`**

Copy `docker-compose.site.yml` then:

1. Delete `uns_simulator` and `spb_mapper_client`.
2. From `uns_frontend` `depends_on`, delete `uns_simulator`.
3. From `uns_prometheus` `depends_on`, delete `uns_simulator`.
4. Change broker:

```yaml
  uns_mqtt_broker:
    image: "hivemq/hivemq-ce:latest"
    ports:
      - "${SITE_MQTT_PORT:-1893}:1883"
    volumes:
      - ${HIVEMQ_CONFIG:-./conf/hivemq/enterprise.xml}:/opt/hivemq/conf/config.xml:ro
    networks:
      default:
        aliases:
          - enterprise_mqtt
    healthcheck:
      test: ["CMD-SHELL", "timeout 2 bash -c 'echo > /dev/tcp/127.0.0.1/1883' || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 90s
```

5. Restore `uns_kafka_broker` and `kafka_mapper_client` from `docker-compose.yml` (same image, same `9092:9092`, same `UNS_kafka__config`). Restore `graphql_server` `UNS_kafka__config` and `depends_on.uns_kafka_broker`.
6. Keep the same `${SITE_*}` and `CONSOLE_ORIGIN` interpolations as the site file.
7. Same external network `uns_enterprise`.
8. Do not publish an Edge console port.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./00_uns_config/test/test_site_enterprise_mesh.py -v`

Expected: all PASS.

Also run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py ./00_uns_config/test/test_compose_env.py -v`

Expected: PASS (single-Instance contracts unchanged).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.enterprise.yml 11_frontend/nginx.conf 00_uns_config/test/test_site_enterprise_mesh.py
git commit -m "feat(compose): add HiveMQ CE enterprise twin"
```

---

### Task 6: `uns_compose --instance`

**Files:**
- Modify: `00_uns_config/src/uns_config/compose_env.py`
- Modify: `00_uns_config/test/test_compose_env.py`

**Interfaces:**
- Consumes: `conf/instances/<name>/compose.env`
- Produces: `split_instance_args(argv: list[str]) -> tuple[str | None, list[str]]`; `INSTANCE_NETWORK = "uns_enterprise"`; `VALID_INSTANCES = frozenset({"site1", "site2", "site3", "enterprise"})`

- [ ] **Step 1: Write the failing tests**

Append to `00_uns_config/test/test_compose_env.py`:

```python
from uns_config.compose_env import VALID_INSTANCES, split_instance_args


def test_split_instance_args_strips_flag():
    instance, rest = split_instance_args(
        ["--instance", "site2", "-f", "docker-compose.site.yml", "up", "-d"]
    )
    assert instance == "site2"
    assert rest == ["-f", "docker-compose.site.yml", "up", "-d"]


def test_split_instance_args_equals_form():
    instance, rest = split_instance_args(["--instance=enterprise", "ps"])
    assert instance == "enterprise"
    assert rest == ["ps"]


def test_split_instance_args_none_when_absent():
    instance, rest = split_instance_args(["-f", "docker-compose.yml", "up", "-d"])
    assert instance is None
    assert rest == ["-f", "docker-compose.yml", "up", "-d"]


def test_valid_instances_are_the_four_projects():
    assert VALID_INSTANCES == frozenset({"site1", "site2", "site3", "enterprise"})
```

Run: `uv run pytest ./00_uns_config/test/test_compose_env.py::test_split_instance_args_strips_flag -v`

Expected: FAIL — `split_instance_args` not defined.

- [ ] **Step 2: Implement**

Add to `compose_env.py` (above `main`):

```python
INSTANCE_NETWORK = "uns_enterprise"
VALID_INSTANCES = frozenset({"site1", "site2", "site3", "enterprise"})


def split_instance_args(argv: list[str]) -> tuple[str | None, list[str]]:
    """Strip ``--instance NAME`` from argv. Remaining args go to docker compose."""
    instance: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--instance":
            if i + 1 >= len(argv):
                raise SystemExit("uns_compose --instance requires a name")
            instance = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--instance="):
            instance = arg.split("=", 1)[1]
            i += 1
            continue
        rest.append(arg)
        i += 1
    if instance is not None and instance not in VALID_INSTANCES:
        raise SystemExit(
            f"unknown instance {instance!r}; expected one of "
            + ", ".join(sorted(VALID_INSTANCES))
        )
    return instance, rest


def _ensure_instance_network(docker: str) -> None:
    subprocess.run(
        [docker, "network", "inspect", INSTANCE_NETWORK],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    inspect = subprocess.run(
        [docker, "network", "inspect", INSTANCE_NETWORK],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode != 0:
        created = subprocess.run(
            [docker, "network", "create", INSTANCE_NETWORK],
            check=False,
        )
        if created.returncode != 0:
            raise SystemExit(f"could not create docker network {INSTANCE_NETWORK}")
```

Replace `main` with:

```python
def main() -> None:
    """Run ``docker compose`` with secrets loaded from conf/.secrets.yaml."""
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("docker is not on PATH")

    instance, compose_args = split_instance_args(sys.argv[1:] or ["up", "-d"])
    env = {**os.environ, **compose_environment()}
    cmd = [docker, "compose", *compose_args]

    if instance is not None:
        _ensure_instance_network(docker)
        env["COMPOSE_PROJECT_NAME"] = instance
        env_file = Path(__file__).resolve().parents[3] / "conf" / "instances" / instance / "compose.env"
        if not env_file.is_file():
            raise SystemExit(f"missing {env_file}")
        cmd = [docker, "compose", "--env-file", str(env_file), *compose_args]

    completed = subprocess.run(cmd, env=env, check=False)
    raise SystemExit(completed.returncode)
```

Add `from pathlib import Path` to the imports.

Fix `_ensure_instance_network` to inspect once:

```python
def _ensure_instance_network(docker: str) -> None:
    inspect = subprocess.run(
        [docker, "network", "inspect", INSTANCE_NETWORK],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode == 0:
        return
    created = subprocess.run(
        [docker, "network", "create", INSTANCE_NETWORK],
        check=False,
    )
    if created.returncode != 0:
        raise SystemExit(f"could not create docker network {INSTANCE_NETWORK}")
```

Use only this single-inspect version in the file (do not leave the doubled inspect from the first snippet).

`parents[3]`: `compose_env.py` lives at `00_uns_config/src/uns_config/compose_env.py` → parents[0]=uns_config, [1]=src, [2]=00_uns_config, [3]=repo root. Correct.

- [ ] **Step 3: Run tests**

Run: `uv run pytest ./00_uns_config/test/test_compose_env.py ./00_uns_config/test/test_site_enterprise_mesh.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add 00_uns_config/src/uns_config/compose_env.py 00_uns_config/test/test_compose_env.py
git commit -m "feat(compose): uns_compose --instance starts a named mesh stack"
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (Architecture + Local Docker Compose stack)
- Modify: `conf/hivemq/README.md`
- Modify: `docs/adr/0010-site-instance-and-enterprise-cloud-hop.md`
- Modify: `docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md` (Status line; persist)

**Interfaces:**
- Consumes: port table and commands from Tasks 3–6
- Produces: operator-facing mesh instructions

- [ ] **Step 1: README — after the Architecture block, add a mesh subsection**

```markdown
### Laptop mesh (three sites + enterprise)

Needs a high-RAM machine. Daily work stays `npm run stack` (one Instance).

```bash
uv run uns_compose --instance enterprise -f docker-compose.enterprise.yml up -d --build
uv run uns_compose --instance site1 -f docker-compose.site.yml up -d --build
uv run uns_compose --instance site2 -f docker-compose.site.yml up -d --build
uv run uns_compose --instance site3 -f docker-compose.site.yml up -d --build
```

Consoles: site1 `http://localhost:8088`, site2 `8188`, site3 `8288`, enterprise `8388` (Grafana at each `/grafana`). Enterprise MQTT is `1893`. Kafka (analytics seam, not AWS itself) is `9092` on enterprise only.

Stop one project: `uv run uns_compose --instance site2 -f docker-compose.site.yml down`.
```

Include the host-port table from the spec. State that four full stacks can exhaust a laptop. State that CE bridge persist is commercial — a WAN outage drops live forwards; each site Timescale still has what it stored.

- [ ] **Step 2: `conf/hivemq/README.md`**

Add after the opening paragraph:

```markdown
Mesh XML (not used by `npm run stack`):

- `site1.xml` / `site2.xml` / `site3.xml` — Edge plus MQTT bridge `#` → `enterprise_mqtt`
- `enterprise.xml` — HiveMQ CE listener only. No adapters, no Control Center port.
```

- [ ] **Step 3: ADR 0010 Consequences — append**

```markdown
- The laptop mesh (three Site Instances + one Enterprise Instance) is specified in
  `docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md`.
  Edge bridge offline persist is commercial; OSS forwards live only.
```

- [ ] **Step 4: Spec status and persist correction**

Set `Status: Approved`.

In §2 decision 6 replace “File persistence on the bridge so a WAN outage does not drop site publishes that already reached Edge” with “OSS Edge forwards live only. `<persist>true</persist>` is commercial and must not appear in checked-in XML. The site historian still holds Historic Events when CE is down.”

In §7 “Enterprise down” row replace the persist sentence with: “Edge does not spool the bridge. New publishes after CE is down do not arrive at enterprise until CE returns. Site Timescale and Grafana keep working.”

- [ ] **Step 5: Commit**

```bash
git add README.md conf/hivemq/README.md docs/adr/0010-site-instance-and-enterprise-cloud-hop.md docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md
git commit -m "docs: describe the site and enterprise Compose mesh"
```

---

## Manual verification (not CI)

On a high-RAM machine, after Task 7:

1. `uv run uns_compose --instance enterprise -f docker-compose.enterprise.yml up -d --build`
2. Start `site1`, `site2`, `site3` the same way with `-f docker-compose.site.yml`.
3. Site consoles show only their `AcmeWater/SiteN` tree.
4. `http://localhost:8388` and `8388/grafana` show all three prefixes.
5. `uv run uns_compose --instance enterprise -f docker-compose.enterprise.yml down` — site consoles still update.
6. Bring enterprise back — new messages appear on CE / enterprise Timescale / Kafka (`9092`).
7. `npm run down` / `npm run stack` still starts the single Instance on `8088` / `1883`.

Do not log into AWS or Azure.

---

## Self-review

| Spec item | Task |
| --- | --- |
| Same repo / same console | Global + Task 5 nginx only |
| Two compose files, four projects | 4, 5, 6 |
| Site services / no Kafka | 4 |
| Enterprise twin + CE + Kafka | 5 |
| Three full sites | 3 env files + 6 |
| Bridge `#` → `enterprise_mqtt`, `{#}` | 2 |
| Grafana `/grafana`, Prometheus ports | 3, 4 |
| No CE console port 18093 | 3, 5 |
| File-contract tests, no mesh in CI | 1 |
| `uns_compose --instance` | 6 |
| README / ADR / spec persist correction | 7 |
| No AWS/Azure | Global + manual |
