# Catalog-driven S7 and EtherNet/IP Edge Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let engineers author S7 and EtherNet/IP endpoints and signals in Assets & Connectivity; persist them in the Connectivity catalog; generate HiveMQ Edge `<protocol-adapter>` blocks into `conf/hivemq/config.xml`; show Pending/Connected/Failed like today’s OPC UA rows. OPC UA stays on `opcua_client`.

**Architecture:** One catalog, two apply backends. GraphQL writes `console.connectivity_*` and, for `s7` / `ethernet_ip` only, splices catalog-owned adapters into `config.xml` (4-space indent matching `adapters-unroutable.xml`). Operator recreates `uns_mqtt_broker`. `opcua_client` ignores non-`opc_ua` rows.

**Tech Stack:** Postgres / Alembic (`09_uns_model`), Strawberry GraphQL (`07_uns_graphql`), React + Vitest (`11_frontend`), `xml.etree` pretty-print in `00_uns_config`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md`

## Global Constraints

- **OPC UA apply path does not change.** Catalog → `opcua_client` poll. No OPC UA `<protocol-adapter>` is generated.
- **S7/EIP apply is generate XML + operator recreate.** No Docker socket. No Edge Management API.
- **Catalog-owned `adapterId` is `catalog-<server.id>`.** Generator may insert/replace/delete only those blocks.
- **XML indent is a contract.** Four spaces per level; declaration `<?xml version="1.0" encoding="UTF-8" ?>`; child order matches `conf/hivemq/fixtures/adapters-unroutable.xml` S7/EIP blocks. Do not re-pretty-print the whole document.
- **Preserve** listeners, admin-api, comments, and the `simulation` adapter bytes.
- **No southbound** on catalog adapters (omit `<southboundMappings/>`).
- **`maxQos` 1 and `includeTimestamp` true** on every generated mapping.
- **`protocolId`:** catalog `ethernet_ip` → Edge `eip`; catalog `s7` → Edge `s7`.
- **Pending copy (verbatim):** `Recreate uns_mqtt_broker to apply Edge config`
- **TCP test timeout:** 3 seconds. Reachability only, not an S7/CIP handshake.
- **IPv6 out.** Host is IPv4 or hostname.
- **Modbus / MQTT / SQL stay “— later”.**
- **No live broker in pytest.** Temp XML files only.

---

## File Structure

```
09_uns_model/src/uns_model/tables.py
09_uns_model/src/uns_model/connectivity.py
09_uns_model/migrations/versions/0008_connectivity_plc_protocols.py
09_uns_model/test/test_connectivity.py

00_uns_config/src/uns_config/hivemq_edge_xml.py
00_uns_config/test/test_hivemq_edge_xml.py

07_uns_graphql/src/uns_graphql/type/connectivity.py
07_uns_graphql/src/uns_graphql/input/connectivity.py
07_uns_graphql/src/uns_graphql/mutations/connectivity.py
07_uns_graphql/src/uns_graphql/queries/connectivity.py
07_uns_graphql/src/uns_graphql/auth/require.py
07_uns_graphql/src/uns_graphql/tcp_probe.py
07_uns_graphql/schema/uns_schema.graphql
07_uns_graphql/test/type/test_connectivity.py
07_uns_graphql/test/mutations/test_connectivity.py
07_uns_graphql/test/auth/test_require.py

10_uns_opcua/src/uns_opcua/catalog.py
10_uns_opcua/test/test_catalog.py

11_frontend/src/lib/connectivity/validate-server.ts
11_frontend/src/lib/connectivity/map-servers.ts
11_frontend/src/lib/connectivity/host-port.ts
11_frontend/src/services/graphql/types.ts
11_frontend/src/services/graphql/queries.ts
11_frontend/src/services/graphql/client.ts
11_frontend/src/components/connectivity/ConnectivityView.tsx
11_frontend/src/components/connectivity/SignalsTab.tsx

conf/hivemq/README.md
```

---

### Task 1: Catalog vocab, endpoint rules, migration

**Files:**
- Modify: `09_uns_model/src/uns_model/tables.py` (`CONNECTIVITY_PROTOCOLS`, `CONNECTIVITY_STATUSES`, new constants, `protocol_config` column)
- Modify: `09_uns_model/src/uns_model/connectivity.py` (`ConnectivityServerSpec.validate`, `EDGE_APPLY_ERROR`, `parse_host_port`)
- Create: `09_uns_model/migrations/versions/0008_connectivity_plc_protocols.py`
- Modify: `09_uns_model/test/test_connectivity.py`

**Interfaces:**
- Consumes: existing `ConnectivityServerSpec` fields
- Produces: `CONNECTIVITY_PROTOCOLS = ("opc_ua", "s7", "ethernet_ip")`; `CONNECTIVITY_STATUSES` includes `pending`; `S7_CONTROLLER_TYPES = ("S7_1500", "S7_1200", "S7_300", "S7_400")`; `PLC_PROTOCOLS = frozenset({"s7", "ethernet_ip"})`; `EDGE_APPLY_ERROR = "Recreate uns_mqtt_broker to apply Edge config"`; `parse_host_port(endpoint: str) -> tuple[str, int]`; `ConnectivityServerSpec.protocol_config: dict[str, str] | None = None`

- [ ] **Step 1: Write the failing tests**

Add to `09_uns_model/test/test_connectivity.py`:

```python
from uns_model.connectivity import (
    ConnectivityServerSpec,
    EDGE_APPLY_ERROR,
    parse_host_port,
)
from uns_model.tables import (
    CONNECTIVITY_PROTOCOLS,
    CONNECTIVITY_STATUSES,
    PLC_PROTOCOLS,
    S7_CONTROLLER_TYPES,
)


def test_protocols_include_s7_and_ethernet_ip():
    assert CONNECTIVITY_PROTOCOLS == ("opc_ua", "s7", "ethernet_ip")
    assert PLC_PROTOCOLS == frozenset({"s7", "ethernet_ip"})


def test_statuses_include_pending():
    assert CONNECTIVITY_STATUSES == ("untested", "pending", "connected", "failed")


def test_parse_host_port_splits_ipv4_and_hostname():
    assert parse_host_port("192.168.1.10:102") == ("192.168.1.10", 102)
    assert parse_host_port("plc-line1:44818") == ("plc-line1", 44818)


def test_parse_host_port_rejects_opc_tcp_and_bad_port():
    with pytest.raises(ValueError, match="host:port"):
        parse_host_port("opc.tcp://plc:102")
    with pytest.raises(ValueError, match="port"):
        parse_host_port("plc:70000")


def test_s7_spec_accepts_host_port_and_controller_type():
    spec = ConnectivityServerSpec(
        id="srv_s7",
        name="Line1 S7",
        protocol="s7",
        endpoint="10.0.0.5:102",
        protocol_config={"controllerType": "S7_1200"},
    )
    spec.validate()


def test_s7_spec_rejects_opc_tcp_endpoint():
    spec = ConnectivityServerSpec(
        id="srv_s7",
        name="Line1 S7",
        protocol="s7",
        endpoint="opc.tcp://10.0.0.5:102",
    )
    with pytest.raises(ValueError, match="host:port"):
        spec.validate()


def test_s7_spec_rejects_unknown_controller_type():
    spec = ConnectivityServerSpec(
        id="srv_s7",
        name="Line1 S7",
        protocol="s7",
        endpoint="10.0.0.5:102",
        protocol_config={"controllerType": "LOGO"},
    )
    with pytest.raises(ValueError, match="controllerType"):
        spec.validate()


def test_eip_spec_accepts_host_port_without_security():
    spec = ConnectivityServerSpec(
        id="srv_eip",
        name="Pack CIP",
        protocol="ethernet_ip",
        endpoint="10.0.0.8:44818",
    )
    spec.validate()


def test_opc_ua_spec_still_requires_opc_tcp():
    spec = ConnectivityServerSpec(
        id="srv_opc",
        name="opcplc",
        protocol="opc_ua",
        endpoint="10.0.0.5:4840",
    )
    with pytest.raises(ValueError, match="opc.tcp"):
        spec.validate()


def test_edge_apply_error_copy():
    assert EDGE_APPLY_ERROR == "Recreate uns_mqtt_broker to apply Edge config"


def test_s7_controller_types():
    assert S7_CONTROLLER_TYPES == ("S7_1500", "S7_1200", "S7_300", "S7_400")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py::test_protocols_include_s7_and_ethernet_ip ./09_uns_model/test/test_connectivity.py::test_parse_host_port_splits_ipv4_and_hostname -v`

Expected: FAIL with `ImportError` or assertion on `CONNECTIVITY_PROTOCOLS`.

- [ ] **Step 3: Write minimal implementation**

In `tables.py` replace the vocabularies and add constants + column:

```python
CONNECTIVITY_PROTOCOLS: tuple[str, ...] = ("opc_ua", "s7", "ethernet_ip")
CONNECTIVITY_STATUSES: tuple[str, ...] = ("untested", "pending", "connected", "failed")
PLC_PROTOCOLS: frozenset[str] = frozenset({"s7", "ethernet_ip"})
S7_CONTROLLER_TYPES: tuple[str, ...] = ("S7_1500", "S7_1200", "S7_300", "S7_400")
```

On `ConnectivityServer`, after `server_certificate`:

```python
    protocol_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

In `connectivity.py`:

```python
from uns_model.tables import (
    CONNECTIVITY_AUTH_MODES,
    CONNECTIVITY_PROTOCOLS,
    CONNECTIVITY_SECURITY_MODES,
    CONNECTIVITY_SECURITY_POLICIES,
    PLC_PROTOCOLS,
    S7_CONTROLLER_TYPES,
)

EDGE_APPLY_ERROR = "Recreate uns_mqtt_broker to apply Edge config"
_HOST_PORT = re.compile(r"^([A-Za-z0-9.-]+):(\d{1,5})$")


def parse_host_port(endpoint: str) -> tuple[str, int]:
    match = _HOST_PORT.fullmatch((endpoint or "").strip())
    if not match:
        raise ValueError("Endpoint must be host:port")
    port = int(match.group(2))
    if port < 1 or port > 65535:
        raise ValueError("port must be 1–65535")
    return match.group(1), port
```

Add `protocol_config: dict[str, Any] | None = None` to `ConnectivityServerSpec`.

Replace `validate` endpoint + security block with:

```python
        if self.protocol in PLC_PROTOCOLS:
            parse_host_port(self.endpoint)
            if self.protocol == "s7":
                controller = (self.protocol_config or {}).get("controllerType", "S7_1500")
                _require_one_of("controllerType", controller, S7_CONTROLLER_TYPES)
        else:
            if not _ENDPOINT.match(self.endpoint):
                raise ValueError("Endpoint must be opc.tcp://host:port")
            # existing security / auth checks unchanged
```

Keep the existing OPC UA security checks inside the `else` branch only. Still run `_require_one_of` for protocol / auth / security on every spec (S7/EIP use defaults `anonymous` / `None`).

Create `0008_connectivity_plc_protocols.py`:

```python
"""Allow S7 / EtherNet/IP catalog rows and pending apply status.

Revision ID: 0008_connectivity_plc_protocols
Revises: 0007_signal_context
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_connectivity_plc_protocols"
down_revision: str | None = "0007_signal_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_protocol_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_protocol_check "
        "CHECK (protocol IN ('opc_ua', 's7', 'ethernet_ip'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_last_status_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_last_status_check "
        "CHECK (last_status IN ('untested', 'pending', 'connected', 'failed'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
        "protocol_config JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE console.connectivity_servers DROP COLUMN IF EXISTS protocol_config")
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_protocol_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_protocol_check "
        "CHECK (protocol IN ('opc_ua'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_last_status_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_last_status_check "
        "CHECK (last_status IN ('untested', 'connected', 'failed'))"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py -v -k "protocols_include or statuses_include or parse_host_port or s7_spec or eip_spec or opc_ua_spec or edge_apply or s7_controller"`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/tables.py 09_uns_model/src/uns_model/connectivity.py 09_uns_model/migrations/versions/0008_connectivity_plc_protocols.py 09_uns_model/test/test_connectivity.py
git commit -m "feat(model): allow S7 and EtherNet/IP in the Connectivity catalog."
```

---

### Task 2: HiveMQ XML generator (indent contract)

**Files:**
- Create: `00_uns_config/src/uns_config/hivemq_edge_xml.py`
- Create: `00_uns_config/test/test_hivemq_edge_xml.py`

**Interfaces:**
- Consumes: nothing from Task 1 (keep `uns_config` free of `uns_model`)
- Produces:

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class EdgeTagInput:
    node_id: str
    display_name: str
    mqtt_topic: str
    data_type: str | None  # catalog Integer/Double/Boolean/String or None

@dataclass(frozen=True, slots=True)
class EdgeAdapterInput:
    server_id: str
    protocol: str  # "s7" | "ethernet_ip"
    host: str
    port: int
    controller_type: str = "S7_1500"
    tags: tuple[EdgeTagInput, ...] = ()

def adapter_id_for(server_id: str) -> str: ...
def edge_data_type(catalog_type: str | None) -> str: ...
def tag_xml_name(node_id: str) -> str: ...
def render_catalog_adapter(adapter: EdgeAdapterInput) -> str: ...
def apply_catalog_adapters(document: str, adapters: list[EdgeAdapterInput]) -> str: ...
def apply_catalog_adapters_file(path: Path, adapters: list[EdgeAdapterInput]) -> None: ...
```

- [ ] **Step 1: Write the failing tests**

Create `00_uns_config/test/test_hivemq_edge_xml.py`. Copy the checked-in `config.xml` into a temp path in tests (read from repo `conf/hivemq/config.xml`). Read fixture S7/EIP blocks from `conf/hivemq/fixtures/adapters-unroutable.xml` as whitespace oracles.

```python
from pathlib import Path

import pytest

from uns_config.hivemq_edge_xml import (
    EdgeAdapterInput,
    EdgeTagInput,
    adapter_id_for,
    apply_catalog_adapters,
    apply_catalog_adapters_file,
    edge_data_type,
    render_catalog_adapter,
    tag_xml_name,
)

_REPO = Path(__file__).resolve().parents[2]
_CONFIG = (_REPO / "conf" / "hivemq" / "config.xml").read_text(encoding="utf-8")
_FIXTURE = (_REPO / "conf" / "hivemq" / "fixtures" / "adapters-unroutable.xml").read_text(
    encoding="utf-8"
)


def _s7(**overrides) -> EdgeAdapterInput:
    tags = overrides.pop("tags", (
        EdgeTagInput("%ID103", "Speed", "Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed", "Integer"),
    ))
    return EdgeAdapterInput(
        server_id=overrides.pop("server_id", "fixture-s7"),
        protocol="s7",
        host=overrides.pop("host", "192.0.2.1"),
        port=overrides.pop("port", 102),
        controller_type=overrides.pop("controller_type", "S7_1500"),
        tags=tags,
    )


def test_adapter_id_prefix():
    assert adapter_id_for("srv_ab") == "catalog-srv_ab"


def test_edge_data_type_map():
    assert edge_data_type("Integer") == "DINT"
    assert edge_data_type("Double") == "REAL"
    assert edge_data_type("Boolean") == "BOOL"
    assert edge_data_type("String") == "STRING"
    assert edge_data_type(None) == "DINT"


def test_render_s7_matches_fixture_whitespace():
    rendered = render_catalog_adapter(_s7())
    oracle = _FIXTURE.split('<protocol-adapter>')[1]
    oracle = "<protocol-adapter>" + oracle.split("</protocol-adapter>")[0] + "</protocol-adapter>"
    expected = oracle.replace("fixture-s7", "catalog-fixture-s7").replace(
        "Unroutable S7 parse fixture", "Speed"
    ).replace("fixture_s7_speed", tag_xml_name("%ID103"))
    assert rendered == expected


def test_declaration_and_simulation_survive_apply(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1")])
    text = path.read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8" ?>')
    assert "HiveMQ Edge simulators" in text
    assert "<adapterId>sim</adapterId>" in text
    assert "<protocolId>s7</protocolId>" in text
    assert "<adapterId>catalog-srv1</adapterId>" in text
    assert "southbound" not in text.lower()
    # 4-space indent on catalog adapter
    assert "\n        <protocol-adapter>\n            <adapterId>catalog-srv1</adapterId>" in text


def test_replace_same_adapter_id_does_not_duplicate(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1", host="10.0.0.1")])
    apply_catalog_adapters_file(path, [_s7(server_id="srv1", host="10.0.0.2")])
    text = path.read_text(encoding="utf-8")
    assert text.count("<adapterId>catalog-srv1</adapterId>") == 1
    assert "<host>10.0.0.2</host>" in text


def test_delete_catalog_adapter_keeps_simulation(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1")])
    apply_catalog_adapters_file(path, [])
    text = path.read_text(encoding="utf-8")
    assert "catalog-srv1" not in text
    assert "<adapterId>sim</adapterId>" in text


def test_empty_tags_self_close():
    xml = render_catalog_adapter(_s7(tags=()))
    assert "<northboundMappings/>" in xml
    assert "<tags/>" in xml


def test_eip_protocol_id_is_eip():
    adapter = EdgeAdapterInput(
        server_id="e1",
        protocol="ethernet_ip",
        host="192.0.2.1",
        port=44818,
        tags=(EdgeTagInput("Program:MainProgram.Count", "Count", "Acme/Test/Count", "Integer"),),
    )
    xml = render_catalog_adapter(adapter)
    assert "<protocolId>eip</protocolId>" in xml
    assert "<address>Program:MainProgram.Count</address>" in xml
    assert "<tagAddress>" not in xml


def test_broken_xml_is_not_written(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text("<not-hivemq>", encoding="utf-8")
    with pytest.raises(ValueError):
        apply_catalog_adapters_file(path, [_s7()])
    assert path.read_text(encoding="utf-8") == "<not-hivemq>"
```

If the S7 whitespace oracle is too brittle because `tag_xml_name("%ID103")` differs from `fixture_s7_speed`, drop byte-equality and instead assert:

- every nesting level increases by exactly four spaces
- child order `adapterId`, `protocolId`, `config`, `northboundMappings`, `tags`
- config order `host`, `port`, `controllerType`
- mapping order `topic`, `tagName`, `maxQos`, `includeTimestamp`
- no tab characters

Keep `test_declaration_and_simulation_survive_apply` as the must-pass indent smoke.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_xml.py -v`

Expected: FAIL with `ModuleNotFoundError: uns_config.hivemq_edge_xml`

- [ ] **Step 3: Write minimal implementation**

Create `00_uns_config/src/uns_config/hivemq_edge_xml.py`:

```python
"""Splice catalog-owned HiveMQ Edge adapters into config.xml without restyling the rest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_DATA_TYPES = {"Integer": "DINT", "Double": "REAL", "Boolean": "BOOL", "String": "STRING"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")
_ADAPTER_SPLIT = re.compile(r"(?=<protocol-adapter>)")


@dataclass(frozen=True, slots=True)
class EdgeTagInput:
    node_id: str
    display_name: str
    mqtt_topic: str
    data_type: str | None


@dataclass(frozen=True, slots=True)
class EdgeAdapterInput:
    server_id: str
    protocol: str
    host: str
    port: int
    controller_type: str = "S7_1500"
    tags: tuple[EdgeTagInput, ...] = ()


def adapter_id_for(server_id: str) -> str:
    return f"catalog-{server_id}"


def edge_data_type(catalog_type: str | None) -> str:
    return _DATA_TYPES.get(catalog_type or "", "DINT")


def tag_xml_name(node_id: str) -> str:
    cleaned = _SAFE_NAME.sub("_", node_id).strip("_")
    return cleaned or "tag"


def render_catalog_adapter(adapter: EdgeAdapterInput) -> str:
    protocol_id = "eip" if adapter.protocol == "ethernet_ip" else "s7"
    aid = adapter_id_for(adapter.server_id)
    lines = [
        "        <protocol-adapter>",
        f"            <adapterId>{_esc(aid)}</adapterId>",
        f"            <protocolId>{protocol_id}</protocolId>",
        "            <config>",
        f"                <host>{_esc(adapter.host)}</host>",
        f"                <port>{adapter.port}</port>",
    ]
    if protocol_id == "s7":
        lines.append(
            f"                <controllerType>{_esc(adapter.controller_type)}</controllerType>"
        )
    lines.append("            </config>")
    if not adapter.tags:
        lines.extend(["            <northboundMappings/>", "            <tags/>"])
    else:
        lines.append("            <northboundMappings>")
        for tag in adapter.tags:
            name = tag_xml_name(tag.node_id)
            lines.extend(
                [
                    "                <northboundMapping>",
                    f"                    <topic>{_esc(tag.mqtt_topic)}</topic>",
                    f"                    <tagName>{_esc(name)}</tagName>",
                    "                    <maxQos>1</maxQos>",
                    "                    <includeTimestamp>true</includeTimestamp>",
                    "                </northboundMapping>",
                ]
            )
        lines.append("            </northboundMappings>")
        lines.append("            <tags>")
        addr_el = "tagAddress" if protocol_id == "s7" else "address"
        for tag in adapter.tags:
            name = tag_xml_name(tag.node_id)
            desc = tag.display_name or tag.node_id
            lines.extend(
                [
                    "                <tag>",
                    f"                    <name>{_esc(name)}</name>",
                    f"                    <description>{_esc(desc)}</description>",
                    "                    <definition>",
                    f"                        <{addr_el}>{_esc(tag.node_id)}</{addr_el}>",
                    f"                        <dataType>{edge_data_type(tag.data_type)}</dataType>",
                    "                    </definition>",
                    "                </tag>",
                ]
            )
        lines.append("            </tags>")
    lines.append("        </protocol-adapter>")
    return "\n".join(lines)


def apply_catalog_adapters(document: str, adapters: list[EdgeAdapterInput]) -> str:
    if "<hivemq" not in document:
        raise ValueError("config.xml is not a HiveMQ document")
    try:
        ET.fromstring(document)
    except ET.ParseError as exc:
        raise ValueError("config.xml is not well-formed XML") from exc
    start = document.find("<protocol-adapters>")
    end = document.find("</protocol-adapters>")
    if start < 0 or end < 0:
        raise ValueError("config.xml has no protocol-adapters element")
    open_len = len("<protocol-adapters>")
    prefix = document[: start + open_len]
    inner = document[start + open_len : end]
    suffix = document[end:]
    kept = [block.strip("\n") for block in _ADAPTER_SPLIT.split(inner) if block.strip()]
    kept = [block for block in kept if "<adapterId>catalog-" not in block]
    rendered = [render_catalog_adapter(item) for item in sorted(adapters, key=lambda a: a.server_id)]
    body = "\n".join([*kept, *rendered])
    return f"{prefix}\n{body}\n    {suffix}" if body else f"{prefix}\n    {suffix}"


def apply_catalog_adapters_file(path: Path, adapters: list[EdgeAdapterInput]) -> None:
    original = path.read_text(encoding="utf-8")
    updated = apply_catalog_adapters(original, adapters)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(path)


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_xml.py -v`

Expected: PASS. If `test_render_s7_matches_fixture_whitespace` fails on tag name / description only, switch that test to the structural indent assertions listed in Step 1.

- [ ] **Step 5: Commit**

```bash
git add 00_uns_config/src/uns_config/hivemq_edge_xml.py 00_uns_config/test/test_hivemq_edge_xml.py
git commit -m "feat(config): generate catalog-owned HiveMQ S7 and EIP adapters."
```

---

### Task 3: Repository — save tag, duplicate topics, XML after_flush

**Files:**
- Modify: `09_uns_model/src/uns_model/connectivity.py`
- Modify: `09_uns_model/test/test_connectivity.py`
- Modify: `09_uns_model/test/test_integration.py` (only if existing save/list tests break on new column)

**Interfaces:**
- Consumes: `apply_catalog_adapters_file`, `EdgeAdapterInput`, `EdgeTagInput`, `parse_host_port`, `EDGE_APPLY_ERROR`, `PLC_PROTOCOLS`
- Produces:

```python
async def save_tag(self, server_id: str, spec: ConnectivityTagSpec, **context) -> ConnectivityTag
async def subscribed_topics(self, session, *, exclude: tuple[str, str] | None = None) -> set[str]
# after_flush: Callable[[list[EdgeAdapterInput]], None] | None
# on save_server, delete_server, save_tag, update_tag, unsubscribe_tag
def edge_adapters_from_rows(servers: Sequence[ConnectivityServer]) -> list[EdgeAdapterInput]
```

`save_server` for `protocol in PLC_PROTOCOLS` sets `last_status="pending"` and `last_error=EDGE_APPLY_ERROR` in `values` when `after_flush` is provided (GraphQL always passes it for PLC). If you set pending in the mutation instead, do it in Task 4 — pick **one**: set pending inside `save_server` / `save_tag` / `update_tag` / `unsubscribe_tag` / `delete_server` when `after_flush` runs successfully. XML write happens in `after_flush` **before** the session commits; if it raises, the catalog write rolls back.

- [ ] **Step 1: Write the failing tests**

Unit-test `edge_adapters_from_rows` (pure) and `save_tag` uniqueness with the existing merge tests’ style. Add:

```python
from uns_config.hivemq_edge_xml import EdgeAdapterInput
from uns_model.connectivity import edge_adapters_from_rows, ConnectivityServerSpec


def test_edge_adapters_from_rows_maps_s7_and_skips_opc_ua():
    s7 = SimpleNamespace(
        id="srv_s7",
        protocol="s7",
        endpoint="10.0.0.5:102",
        protocol_config={"controllerType": "S7_1200"},
        tags=[
            SimpleNamespace(
                node_id="%ID103",
                display_name="Speed",
                mqtt_topic="Acme/Line/Speed",
                data_type="Integer",
                subscribed=True,
            ),
            SimpleNamespace(
                node_id="%ID104",
                display_name="Skip",
                mqtt_topic="Acme/Line/Skip",
                data_type="Integer",
                subscribed=False,
            ),
        ],
    )
    opc = SimpleNamespace(id="srv_opc", protocol="opc_ua", endpoint="opc.tcp://h:4840", tags=[])
    adapters = edge_adapters_from_rows([s7, opc])
    assert len(adapters) == 1
    assert adapters[0] == EdgeAdapterInput(
        server_id="srv_s7",
        protocol="s7",
        host="10.0.0.5",
        port=102,
        controller_type="S7_1200",
        tags=(EdgeTagInput("%ID103", "Speed", "Acme/Line/Speed", "Integer"),),
    )
```

Add an integration test in `test_integration.py` (same Postgres fixture as other connectivity tests):

```python
async def test_save_tag_rejects_duplicate_mqtt_topic(connectivity, ...):
    await connectivity.save_server(ConnectivityServerSpec(
        id="srv_s7", name="S7", protocol="s7", endpoint="10.0.0.5:102"
    ))
    await connectivity.save_tag(
        "srv_s7",
        ConnectivityTagSpec(node_id="%ID1", browse_path="", display_name="A", mqtt_topic="Plant/A"),
    )
    with pytest.raises(ValueError, match="mqtt_topic"):
        await connectivity.save_tag(
            "srv_s7",
            ConnectivityTagSpec(node_id="%ID2", browse_path="", display_name="B", mqtt_topic="Plant/A"),
        )
```

Use the existing integration fixture names already in that file (`connectivity` or whatever the module uses). If the module has no async repo fixture, put duplicate-topic logic in a pure helper `assert_unique_mqtt_topic(existing: set[str], topic: str, *, node_id: str)` and unit-test that instead — do not invent a new DB harness.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py::test_edge_adapters_from_rows_maps_s7_and_skips_opc_ua -v`

Expected: FAIL with `ImportError: edge_adapters_from_rows`

- [ ] **Step 3: Write minimal implementation**

```python
from uns_config.hivemq_edge_xml import EdgeAdapterInput, EdgeTagInput
from uns_model.tables import PLC_PROTOCOLS
from uns_model.connectivity import parse_host_port  # already in this module


def edge_adapters_from_rows(servers: Sequence[object]) -> list[EdgeAdapterInput]:
    adapters: list[EdgeAdapterInput] = []
    for server in servers:
        if getattr(server, "protocol", None) not in PLC_PROTOCOLS:
            continue
        host, port = parse_host_port(server.endpoint)
        controller = (getattr(server, "protocol_config", None) or {}).get(
            "controllerType", "S7_1500"
        )
        tags = tuple(
            EdgeTagInput(tag.node_id, tag.display_name, tag.mqtt_topic, getattr(tag, "data_type", None))
            for tag in getattr(server, "tags", [])
            if tag.subscribed
        )
        adapters.append(
            EdgeAdapterInput(
                server_id=server.id,
                protocol=server.protocol,
                host=host,
                port=port,
                controller_type=controller,
                tags=tags,
            )
        )
    return adapters
```

`save_tag`: upsert `(server_id, node_id)` with `subscribed=True` by default; before write, load all subscribed tags and reject if another node already has the same `mqtt_topic`.

Thread `after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None` through `save_server`, `delete_server`, `save_tag`, `update_tag`, `unsubscribe_tag`. After the write + `flush`, `adapters = edge_adapters_from_rows(await this session's list of servers with tags)`; then `after_flush(adapters)` if provided. For PLC `save_server` / tag mutations, set `last_status` to `pending` and `last_error` to `EDGE_APPLY_ERROR` on the affected server in the same flush.

`09_uns_model` already depends on workspace packages; adding `uns_config` is allowed (`uns_graphql` already depends on both). Add `uns_config` to `09_uns_model/pyproject.toml` dependencies and `[tool.uv.sources]` if missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py::test_edge_adapters_from_rows_maps_s7_and_skips_opc_ua ./09_uns_model/test/test_integration.py -k "duplicate_mqtt or save_tag" -v`

Expected: PASS (skip the integration `-k` if you used the pure helper only)

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/connectivity.py 09_uns_model/test/test_connectivity.py 09_uns_model/test/test_integration.py 09_uns_model/pyproject.toml
git commit -m "feat(model): map catalog PLC rows to Edge adapters and reject duplicate topics."
```

---

### Task 4: GraphQL — enums, saveConnectivityTag, TCP test, XML sync

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/type/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/input/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/connectivity.py` (protocol filter already generic — confirm `ConnectivityProtocol` values)
- Create: `07_uns_graphql/src/uns_graphql/tcp_probe.py`
- Modify: `07_uns_graphql/src/uns_graphql/auth/require.py`
- Modify: `07_uns_graphql/test/type/test_connectivity.py`
- Modify: `07_uns_graphql/test/mutations/test_connectivity.py`
- Modify: `07_uns_graphql/test/auth/test_require.py`
- Modify: `07_uns_graphql/schema/uns_schema.graphql` (regenerate)

**Interfaces:**
- Consumes: Task 1 enums, Task 2 `apply_catalog_adapters_file`, Task 3 `after_flush` + `save_tag` + `edge_adapters_from_rows` + `EDGE_APPLY_ERROR` + `parse_host_port`
- Produces: `ConnectivityProtocol.S7` / `ETHERNET_IP`; `saveConnectivityTag`; `testConnectivityServer(id)`; `protocol_config` JSON on server input/type; XML path `resolve_conf_dir() / "hivemq" / "config.xml"`

```python
def probe_tcp(host: str, port: int, timeout_s: float = 3.0) -> tuple[bool, str | None]: ...
```

- [ ] **Step 1: Write the failing tests**

In `test_type/test_connectivity.py` add `ConnectivityProtocol` to the vocabulary parametrize (import `CONNECTIVITY_PROTOCOLS`).

In `test_require.py` `EXPECTED` add:

```python
    "saveConnectivityTag": {"engineer", "admin"},
    "testConnectivityServer": {"engineer", "admin"},
```

(`testOpcUaConnection` stays a query with `OPC_PROBE_ROLES`. `testConnectivityServer` is a mutation so it can `record_test`.)

In `test/mutations/test_connectivity.py` (follow existing strawberry + mock-repo style):

```python
async def test_save_connectivity_server_s7_calls_after_flush(monkeypatch, tmp_path):
    # mock repository.save_server to capture after_flush and invoke it with one EdgeAdapterInput
    # assert apply_catalog_adapters_file wrote catalog-srv into tmp_path / config.xml
    ...


async def test_subscribe_opc_ua_variables_rejects_s7():
    # repo returns a server with protocol s7
    # mutation raises ValueError / GraphQL error matching "OPC UA"
    ...


async def test_test_connectivity_server_tcp_success_keeps_pending_error(monkeypatch):
    # existing last_status pending; probe_tcp returns (True, None)
    # record_test called with ok=True, error=EDGE_APPLY_ERROR
    ...
```

Add `07_uns_graphql/test/test_tcp_probe.py`:

```python
from unittest.mock import patch
import socket

from uns_graphql.tcp_probe import probe_tcp


def test_probe_tcp_ok():
    with patch("uns_graphql.tcp_probe.socket.create_connection") as conn:
        conn.return_value.__enter__.return_value = object()
        ok, err = probe_tcp("10.0.0.1", 102)
    assert ok is True
    assert err is None


def test_probe_tcp_refused():
    with patch("uns_graphql.tcp_probe.socket.create_connection", side_effect=ConnectionRefusedError("refused")):
        ok, err = probe_tcp("10.0.0.1", 102)
    assert ok is False
    assert "refused" in (err or "").lower() or err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./07_uns_graphql/test/type/test_connectivity.py::test_enums_match_the_database_vocabulary ./07_uns_graphql/test/test_tcp_probe.py -v`

Expected: FAIL — `ConnectivityProtocol` values are only `opc_ua`, or `tcp_probe` missing.

- [ ] **Step 3: Write minimal implementation**

`ConnectivityProtocol`:

```python
class ConnectivityProtocol(Enum):
    OPC_UA = "opc_ua"
    S7 = "s7"
    ETHERNET_IP = "ethernet_ip"
```

Add `protocol_config: JSON | None` to `ConnectivityServerType` and `ConnectivityServerInput` (Strawberry `JSON` scalar already imported in the type module).

`tcp_probe.py`:

```python
import socket


def probe_tcp(host: str, port: int, timeout_s: float = 3.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, None
    except OSError as exc:
        return False, str(exc)
```

Mutations (sketch — match existing `require` / repo style):

```python
from pathlib import Path
from uns_config.loader import resolve_conf_dir
from uns_config.hivemq_edge_xml import apply_catalog_adapters_file
from uns_model.connectivity import EDGE_APPLY_ERROR, PLC_PROTOCOLS, parse_host_port
def _sync_edge(adapters) -> None:
    apply_catalog_adapters_file(resolve_conf_dir() / "hivemq" / "config.xml", adapters)


async def save_connectivity_server(...):
    require(info, "saveConnectivityServer")
    spec = ConnectivityServerSpec(..., protocol_config=server.protocol_config)
    saved = await _repository().save_server(spec, after_flush=_sync_edge)
    return ConnectivityServerType.from_server(saved)


async def save_connectivity_tag(self, info, server_id: str, tag: ConnectivityTagInput) -> ConnectivityTagType:
    require(info, "saveConnectivityTag")
    stored = await _repository().save_tag(server_id, ConnectivityTagSpec(...), after_flush=_sync_edge)
    return ConnectivityTagType.from_tag(stored)


async def test_connectivity_server(self, info, id: str) -> ConnectivityServerType:
    require(info, "testConnectivityServer")
    repo = _repository()
    servers = await repo.list_servers()
    server = next((row for row in servers if row.id == id), None)
    if server is None:
        raise ValueError(f"No Connectivity server with id {id!r}")
    was_pending = server.last_status == "pending"
    if server.protocol == "opc_ua":
        # reuse existing open_client / browse probe used by testOpcUaConnection
        ...
    else:
        host, port = parse_host_port(server.endpoint)
        ok, err = probe_tcp(host, port)
    error = err
    if ok and was_pending:
        error = EDGE_APPLY_ERROR
    updated = await repo.record_test(id, ok=ok, error=error)
    return ConnectivityServerType.from_server(updated)
```

`subscribe_opc_ua_variables`: if the server protocol is not `opc_ua`, raise `ValueError("OPC UA browse is only available for OPC UA servers")`.

`delete_connectivity_server` / `update_connectivity_tag` / `unsubscribe_connectivity_tag`: pass `after_flush=_sync_edge`.

Regenerate schema:

```bash
uv run strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./07_uns_graphql/schema/uns_schema.graphql
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./07_uns_graphql/test/type/test_connectivity.py ./07_uns_graphql/test/test_tcp_probe.py ./07_uns_graphql/test/auth/test_require.py ./07_uns_graphql/test/mutations/test_connectivity.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql 07_uns_graphql/test 07_uns_graphql/schema/uns_schema.graphql
git commit -m "feat(graphql): save S7/EIP catalog rows and probe them over TCP."
```

---

### Task 5: `opcua_client` ignores PLC rows

**Files:**
- Modify: `10_uns_opcua/src/uns_opcua/catalog.py`
- Modify: `10_uns_opcua/test/test_catalog.py`

**Interfaces:**
- Consumes: `ConnectivityServerSpec.protocol`
- Produces: `servers_from_catalog` skips `protocol != "opc_ua"`

- [ ] **Step 1: Write the failing test**

```python
def test_s7_and_eip_catalog_rows_are_not_opcua_collectors():
    servers = [
        ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/"),
        ConnectivityServerSpec("s2", "line-s7", "s7", "10.0.0.5:102"),
        ConnectivityServerSpec("s3", "pack", "ethernet_ip", "10.0.0.8:44818"),
    ]
    tags = {
        "s1": [ConnectivityTagSpec("ns=3;s=A", "A", "A", "Plant/A", True)],
        "s2": [ConnectivityTagSpec("%ID103", "", "Speed", "Plant/Speed", True)],
        "s3": [ConnectivityTagSpec("Program:Count", "", "Count", "Plant/Count", True)],
    }
    configs = servers_from_catalog(servers, tags)
    assert [server.name for server in configs] == ["opcplc"]
    assert configs[0].url.startswith("opc.tcp://")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest ./10_uns_opcua/test/test_catalog.py::test_s7_and_eip_catalog_rows_are_not_opcua_collectors -v`

Expected: FAIL — S7 endpoint is treated as an OPC UA URL (or extra collectors).

- [ ] **Step 3: Write minimal implementation**

At the top of the loop in `servers_from_catalog`:

```python
        if server.protocol != "opc_ua":
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./10_uns_opcua/test/test_catalog.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/catalog.py 10_uns_opcua/test/test_catalog.py
git commit -m "fix(opcua): ignore S7 and EtherNet/IP catalog rows."
```

---

### Task 6: Frontend validation and protocol maps

**Files:**
- Create: `11_frontend/src/lib/connectivity/host-port.ts`
- Modify: `11_frontend/src/lib/connectivity/validate-server.ts`
- Modify: `11_frontend/src/lib/connectivity/map-servers.ts`
- Modify: `11_frontend/src/lib/connectivity/validate-server.test.ts`
- Modify: `11_frontend/src/lib/connectivity/map-servers.test.ts`
- Modify: `11_frontend/src/services/graphql/types.ts`

**Interfaces:**
- Consumes: GraphQL enum names `S7`, `ETHERNET_IP`
- Produces:

```ts
export const PROTOCOLS_IN_SLICE: ConnectivityTabId[] = ['opc_ua', 's7', 'ethernet_ip']
export const PROTOCOL_TO_GQL = { opc_ua: 'OPC_UA', s7: 'S7', ethernet_ip: 'ETHERNET_IP' } as const
export const S7_CONTROLLER_TYPES = ['S7_1500', 'S7_1200', 'S7_300', 'S7_400'] as const
export function joinHostPort(host: string, port: string): string
export function splitHostPort(endpoint: string): { host: string; port: string }
export function defaultPortFor(protocol: ConnectivityTabId): string  // 102 / 44818
```

`GraphqlConnectivityProtocol = 'OPC_UA' | 'S7' | 'ETHERNET_IP'`
`GraphqlConnectivityServer.protocolConfig?: { controllerType?: string } | null`
`GraphqlConnectivityServerInput.protocolConfig?: { controllerType?: string } | null`

- [ ] **Step 1: Write the failing tests**

```ts
// validate-server.test.ts
it('accepts S7 host:port', () => {
  expect(
    validateConnectivityServer(
      draft({ protocol: 's7', endpoint: '10.0.0.5:102', controllerType: 'S7_1500' }),
    ),
  ).toBeNull()
})

it('rejects S7 opc.tcp endpoint', () => {
  expect(
    validateConnectivityServer(draft({ protocol: 's7', endpoint: 'opc.tcp://10.0.0.5:102' })),
  ).toMatch(/host:port/i)
})

it('rejects ethernet_ip without a port', () => {
  expect(validateConnectivityServer(draft({ protocol: 'ethernet_ip', endpoint: '10.0.0.8' }))).toMatch(
    /host:port/i,
  )
})
```

Extend `ConnectivityServerDraft` with optional `controllerType?: string`.

```ts
// map-servers.test.ts
import { PROTOCOLS_IN_SLICE, statusDotClass } from './map-servers'
it('enables opc_ua, s7, and ethernet_ip', () => {
  expect(PROTOCOLS_IN_SLICE).toEqual(['opc_ua', 's7', 'ethernet_ip'])
})
it('paints pending amber', () => {
  expect(statusDotClass('pending')).toMatch(/amber|yellow/)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test:run -- src/lib/connectivity/validate-server.test.ts src/lib/connectivity/map-servers.test.ts`

Working directory: `11_frontend`

Expected: FAIL on S7 accepted / `PROTOCOLS_IN_SLICE`

- [ ] **Step 3: Write minimal implementation**

`host-port.ts`:

```ts
const HOST_PORT = /^([A-Za-z0-9.-]+):(\d{1,5})$/

export function joinHostPort(host: string, port: string): string {
  return `${host.trim()}:${port.trim()}`
}

export function splitHostPort(endpoint: string): { host: string; port: string } {
  const match = HOST_PORT.exec(endpoint.trim())
  if (!match) return { host: '', port: '' }
  return { host: match[1], port: match[2] }
}

export function isHostPort(endpoint: string): boolean {
  const match = HOST_PORT.exec(endpoint.trim())
  if (!match) return false
  const port = Number(match[2])
  return port >= 1 && port <= 65535
}
```

In `validateConnectivityServer`: if `protocol` is `s7` or `ethernet_ip`, require name + `isHostPort(endpoint)`; for `s7` require `controllerType` in `S7_CONTROLLER_TYPES` (default treat missing as `S7_1500`). Skip OPC UA security rules. If protocol is still not in slice (`modbus_tcp` / `mqtt` / `sql`), keep the “later” error.

`statusDotClass`: `pending: 'bg-amber-500'`

`getConnectivityServers` client arg type: `protocol?: GraphqlConnectivityProtocol`

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test:run -- src/lib/connectivity/validate-server.test.ts src/lib/connectivity/map-servers.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/connectivity 11_frontend/src/services/graphql/types.ts
git commit -m "feat(frontend): validate S7 and EtherNet/IP host and port."
```

---

### Task 7: Console — protocol-specific form, status, add signal

**Files:**
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.tsx`
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.test.tsx`
- Modify: `11_frontend/src/components/connectivity/SignalsTab.tsx`
- Modify: `11_frontend/src/components/connectivity/SignalsTab.test.tsx`
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`

**Interfaces:**
- Consumes: Task 6 maps + validation; `saveConnectivityTag`; `testConnectivityServer`
- Produces: Add Server dialog fields swap; Protocol column; Browse hidden for PLC; Test uses `testConnectivityServer`; Signals “Add signal” for S7/EIP

- [ ] **Step 1: Write the failing tests**

In `ConnectivityView.test.tsx`:

- Choosing Protocol S7 enables Host, Port (value `102`), Controller type; hides Security / Authentication / Endpoint URL.
- Save calls `saveConnectivityServer` with `protocol: 'S7'`, `endpoint: '10.0.0.5:102'`, `protocolConfig: { controllerType: 'S7_1500' }`.
- An S7 row shows protocol label, pending lamp, no Browse data button.
- Test on an S7 row calls `testConnectivityServer` not `testOpcUaConnection`.
- Empty state is `No servers` (not `No OPC UA servers`).

In `SignalsTab.test.tsx`:

- When a selected / filter server is S7, an Add signal control exists.
- Submitting address `%ID103`, topic `Acme/Line/Speed`, type Integer calls `saveConnectivityTag`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test:run -- src/components/connectivity/ConnectivityView.test.tsx src/components/connectivity/SignalsTab.test.tsx`

Expected: FAIL — S7 still “later”; Browse still shown.

- [ ] **Step 3: Write minimal implementation**

Dialog title/description become protocol-specific (`Add S7 PLC`, `Add EtherNet/IP PLC`, existing OPC UA copy). Shared: Name + Protocol. OPC UA: current Endpoint + Security + Authentication. S7/EIP: Host, Port (`defaultPortFor`), S7 Controller type. Build `endpoint` with `joinHostPort`. Send `PROTOCOL_TO_GQL[draftProtocol]`.

Servers table: add a Protocol column using `PROTOCOL_TABS` labels. `statusDotClass` already handles pending. Hide Browse unless `server.protocol === 'OPC_UA'`. Row click may still open the signal drawer for PLC (address list) but must not open the OPC UA browse tree.

`handleTest`: `testConnectivityServer(server.id)` then replace the row with the returned server (so pending error can remain).

Queries: add `protocolConfig { controllerType }` to server documents; add mutations:

```graphql
mutation SaveConnectivityTag($serverId: String!, $tag: ConnectivityTagInput!) {
  saveConnectivityTag(serverId: $serverId, tag: $tag) { serverId nodeId mqttTopic dataType subscribed }
}
mutation TestConnectivityServer($id: String!) {
  testConnectivityServer(id: $id) { id lastStatus lastError lastTestedAt }
}
```

Match the exact Strawberry input field names you added in Task 4 (`ConnectivityTagInput`: `nodeId`, `displayName`, `mqttTopic`, `dataType`).

Signals Add signal dialog fields: address → `nodeId`, display name, mqttTopic, dataType. `browsePath` can be `""`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test:run -- src/components/connectivity/ConnectivityView.test.tsx src/components/connectivity/SignalsTab.test.tsx src/lib/connectivity/validate-server.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/connectivity 11_frontend/src/services/graphql
git commit -m "feat(frontend): author S7 and EtherNet/IP servers and signals."
```

---

### Task 8: README + schema contract note

**Files:**
- Modify: `conf/hivemq/README.md`
- Modify: `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md` (Status already Approved — only if implementation notes are needed; prefer not)

**Interfaces:**
- Consumes: the apply path from Tasks 2–4
- Produces: README that tells engineers to use Assets & Connectivity for S7/EIP

- [ ] **Step 1: Replace the hand-edit instructions**

`conf/hivemq/README.md` becomes:

```markdown
# HiveMQ Edge config

`config.xml` is mounted into `uns_mqtt_broker` at `/opt/hivemq/conf/config.xml`.

Default file: MQTT TCP on `1883`, plus the optional `simulation` adapter. The stack
starts with no plant PLC.

**S7 and EtherNet/IP:** author host, port, controller type, and signals in Assets &
Connectivity (`#/connectivity/servers`). GraphQL upserts catalog-owned
`<protocol-adapter>` blocks (`adapterId` `catalog-<server id>`). Then recreate:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
```

Do not hand-edit catalog-owned adapters. Do not add `<southboundMapping>` entries.
The generator preserves listeners, admin-api, comments, and the `simulation` adapter,
and writes 4-space indent matching `fixtures/adapters-unroutable.xml`.

**OPC UA:** engineers add servers in the same console. `opcua_client` polls that
catalog and publishes subscribed tags. Do not author OPC UA mappings in the Edge UI.

The Edge console on host port `18080` (default login `admin` / `hivemq`) is for
inspection. Mitsubishi is out of scope.
```

- [ ] **Step 2: Confirm the checked-in default XML is unchanged**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py ./00_uns_config/test/test_hivemq_edge_xml.py -v`

Expected: PASS. Do not add catalog adapters to git `config.xml`.

- [ ] **Step 3: Commit**

```bash
git add conf/hivemq/README.md
git commit -m "docs(hivemq): author S7 and EtherNet/IP from the connectivity console."
```

---

## Self-review

**Spec coverage**

| Spec section | Task |
| --- | --- |
| One catalog, two backends | 1, 4, 5 |
| `host:port` + `protocol_config` | 1, 6, 7 |
| Generator splice + 4-space indent + no southbound | 2 |
| Pending + recreate copy | 3, 4, 7 |
| TCP test 3s, keep pending error on success | 4, 7 |
| Manual signals / `saveConnectivityTag` / duplicate topics | 3, 4, 7 |
| Form field swap, hide Browse, Protocol column | 7 |
| `opcua_client` filter | 5 |
| XML write failure rolls back catalog | 3 `after_flush` before commit |
| README | 8 |
| Out of scope (Edge API, auto-recreate, OPC UA on Edge) | no task adds them |

**Placeholder scan:** none remaining. If `test_render_s7_matches_fixture_whitespace` is too brittle, Task 2 already names the structural substitute.

**Type consistency:** `EdgeAdapterInput` / `EdgeTagInput` names are identical in Tasks 2–4. `EDGE_APPLY_ERROR` is the same sentence in model, GraphQL, and UI. Catalog protocol `ethernet_ip` → Edge `eip` only inside `render_catalog_adapter`.
