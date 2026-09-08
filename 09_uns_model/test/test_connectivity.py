"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and is distributed "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Connectivity catalog: OPC-UA servers and the tags the console subscribes to.

`merge_discovered` is the one decision worth a unit test: when an engineer has
edited an `mqtt_topic`, a re-discovery must not overwrite it. The repository
around it is exercised by the integration tests in `test_integration.py`,
which need a migrated Postgres database.
"""

from __future__ import annotations

import importlib.util
import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from uns_config.hivemq_edge_xml import EdgeAdapterInput, EdgeTagInput

from uns_model.connectivity import (
    ConnectivityRepository,
    ConnectivityServerSpec,
    ConnectivityTagSpec,
    EDGE_APPLY_ERROR,
    assert_unique_mqtt_topic,
    assert_xml_safe,
    edge_adapters_from_rows,
    merge_discovered,
    metric_key_for_tag,
    parse_host_port,
)
from uns_model.tables import (
    CONNECTIVITY_PROTOCOLS,
    CONNECTIVITY_STATUSES,
    EDGE_PROTOCOLS,
    PLC_PROTOCOLS,
    SEEDED_UNITS_OF_MEASURE,
    S7_CONTROLLER_TYPES,
    SIGNAL_DATA_TYPES,
    SIGNAL_SEMANTIC_CLASSES,
)


def test_protocols_include_s7_and_ethernet_ip():
    assert CONNECTIVITY_PROTOCOLS == ("opc_ua", "s7", "ethernet_ip")
    assert PLC_PROTOCOLS == frozenset({"s7", "ethernet_ip"})


def test_edge_protocols_include_opc_ua():
    assert EDGE_PROTOCOLS == frozenset({"s7", "ethernet_ip", "opc_ua"})
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
    assert EDGE_APPLY_ERROR == "Waiting for HiveMQ Edge to apply"


@pytest.mark.asyncio
async def test_record_live_apply_success_clears_pending():
    session = _FakeSession()
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.record_live_apply(["srv_s7"], ok=True)
    assert session.update_values == {
        "last_status": "untested",
        "last_error": "",
        "updated_at": session.update_values["updated_at"],
    }


@pytest.mark.asyncio
async def test_record_live_apply_failure_sets_pending():
    session = _FakeSession()
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.record_live_apply(["srv_s7"], ok=False)
    assert session.update_values == {
        "last_status": "pending",
        "last_error": EDGE_APPLY_ERROR,
        "updated_at": session.update_values["updated_at"],
    }


@pytest.mark.asyncio
async def test_record_live_apply_ignores_empty_server_ids():
    session = _FakeSession()
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.record_live_apply([], ok=True)
    assert session.statements == []


def test_s7_controller_types():
    assert S7_CONTROLLER_TYPES == ("S7_1500", "S7_1200", "S7_300", "S7_400")


def test_seeded_units_include_celsius_and_kwh():
    assert "°C" in SEEDED_UNITS_OF_MEASURE
    assert "kWh" in SEEDED_UNITS_OF_MEASURE
    assert len(SEEDED_UNITS_OF_MEASURE) == len(set(SEEDED_UNITS_OF_MEASURE))


def test_0007_unit_seed_inserts_bind_params_through_the_engine():
    """Alembic 1.19 `Operations.execute` is `(sqltext, *, execution_options=None)`.

    Passing `{"s": symbol}` as a second positional argument raises
    `TypeError: execute() takes 2 positional arguments but 3 were given`.
    Seed inserts must go through `op.get_bind().execute(text(...), params)`.
    """
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0007_signal_context.py"
    spec = importlib.util.spec_from_file_location("rev_0007_signal_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    bind_params: list[object] = []

    class _Bind:
        def execute(self, statement, parameters=None, execution_options=None):  # noqa: ARG002
            bind_params.append(parameters)
            return None

    class _AlembicOp:
        def execute(self, sqltext, *, execution_options=None):  # noqa: ARG002
            return None

        def get_bind(self) -> _Bind:
            return _Bind()

    module.op = _AlembicOp()
    module.upgrade()

    seeded = [params["s"] for params in bind_params if isinstance(params, dict) and "s" in params]
    assert seeded == list(module.SEEDED_UNITS)


def test_semantic_classes_and_data_types_are_the_spec_vocabularies():
    assert SIGNAL_SEMANTIC_CLASSES == (
        "MeasuredValue",
        "EnergyConsumption",
        "CounterOK",
        "CounterNOK",
        "State",
    )
    assert SIGNAL_DATA_TYPES == ("Double", "Boolean", "Integer", "String")


def test_tag_spec_has_optional_data_type_defaulting_to_none():
    spec = ConnectivityTagSpec("%ID103", "", "Speed", "Acme/Line/Speed")
    assert spec.data_type is None
    spec2 = ConnectivityTagSpec("%ID103", "", "Speed", "Acme/Line/Speed", True, "Integer")
    assert spec2.data_type == "Integer"


def test_save_tag_persists_data_type():
    """`save_tag` must write `data_type` so a one-mutation save can set it, no second patch call."""
    source = inspect.getsource(ConnectivityRepository.save_tag)
    values_block = source.split("values: dict[str, Any] = {", 1)[1].split("}", 1)[0]
    assert '"data_type": spec.data_type' in values_block


def test_merge_keeps_edited_topic():
    existing = [ConnectivityTagSpec("ns=3;s=WTP_T101_Level", "RawWater/T101/Level", "Level", "Plant/T101/Level", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=WTP_T101_Level", "RawWater/T101/Level", "Level", "RawWater/T101/Level", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].mqtt_topic == "Plant/T101/Level"


def test_merge_adds_newly_discovered_nodes():
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [
        ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True),
        ConnectivityTagSpec("ns=3;s=B", "Path/B", "B", "Plant/B", True),
    ]
    merged = merge_discovered(existing, discovered)
    by_node = {tag.node_id: tag for tag in merged}
    assert set(by_node) == {"ns=3;s=A", "ns=3;s=B"}
    assert by_node["ns=3;s=A"].mqtt_topic == "Plant/A"
    assert by_node["ns=3;s=B"].mqtt_topic == "Plant/B"


def test_merge_does_not_unsubscribe_missing_nodes():
    """A node absent from a later discovery stays subscribed until `unsubscribe_tag`."""
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered: list[ConnectivityTagSpec] = []
    merged = merge_discovered(existing, discovered)
    assert merged[0].subscribed is True
    assert merged[0].mqtt_topic == "Plant/A"


def test_merge_updates_display_and_browse_path_for_existing_nodes():
    """Discovery may correct a browse path or display name without touching the topic."""
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=A", "Path/A/Renamed", "Tank Level", "Plant/A", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].browse_path == "Path/A/Renamed"
    assert merged[0].display_name == "Tank Level"
    assert merged[0].mqtt_topic == "Plant/A"


def test_metric_key_uses_topic_suffix_under_asset_path():
    assert (
        metric_key_for_tag(
            asset_path="AcmeWater/Site1/Furnace",
            mqtt_topic="AcmeWater/Site1/Furnace/Heater/Temp",
            browse_path="Heater/Temp",
            display_name="Temp",
        )
        == "Heater/Temp"
    )


def test_metric_key_falls_back_to_browse_path_when_topic_is_not_under_asset():
    assert (
        metric_key_for_tag(
            asset_path="AcmeWater/Site1/Furnace",
            mqtt_topic="Server/OpcPlc/Temperature",
            browse_path="Objects/Temperature",
            display_name="Temperature",
        )
        == "Objects/Temperature"
    )


def test_merge_does_not_need_context_fields_to_keep_identity():
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=A", "Path/A/Renamed", "Tank", "Raw/A", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].mqtt_topic == "Plant/A"


def test_metric_key_uses_display_name_when_topic_equals_asset_path():
    assert (
        metric_key_for_tag(
            asset_path="AcmeWater/Site1/Furnace",
            mqtt_topic="AcmeWater/Site1/Furnace",
            browse_path="Heater/Temp",
            display_name="Temp",
        )
        == "Temp"
    )


def test_edge_adapters_from_rows_maps_s7_and_opc_ua():
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
    opc = SimpleNamespace(
        id="srv_opc",
        protocol="opc_ua",
        endpoint="opc.tcp://h:4840",
        protocol_config=None,
        tags=[
            SimpleNamespace(
                node_id="ns=1;i=1004",
                display_name="Temp",
                mqtt_topic="Server/OpcPlc/Temp",
                data_type="Double",
                subscribed=True,
            )
        ],
    )
    adapters = edge_adapters_from_rows([s7, opc])
    assert len(adapters) == 2
    assert adapters[0] == EdgeAdapterInput(
        server_id="srv_s7",
        protocol="s7",
        host="10.0.0.5",
        port=102,
        controller_type="S7_1200",
        tags=(EdgeTagInput("%ID103", "Speed", "Acme/Line/Speed", "Integer"),),
    )
    assert adapters[1] == EdgeAdapterInput(
        server_id="srv_opc",
        protocol="opc_ua",
        host="",
        port=0,
        uri="opc.tcp://h:4840",
        tags=(EdgeTagInput("ns=1;i=1004", "Temp", "Server/OpcPlc/Temp", "Double"),),
    )


def test_edge_adapters_from_rows_defaults_controller_type_and_handles_empty_tags():
    s7 = SimpleNamespace(id="srv_s7", protocol="s7", endpoint="10.0.0.5:102", protocol_config=None, tags=[])
    adapters = edge_adapters_from_rows([s7])
    assert adapters == [
        EdgeAdapterInput(server_id="srv_s7", protocol="s7", host="10.0.0.5", port=102, controller_type="S7_1500")
    ]


def test_edge_adapters_from_rows_returns_empty_for_no_servers():
    assert edge_adapters_from_rows([]) == []


def test_assert_xml_safe_rejects_a_control_character():
    with pytest.raises(ValueError, match="control character"):
        assert_xml_safe("mqtt_topic", "Acme/Line\x01Speed")


def test_assert_xml_safe_allows_tab_newline_cr_and_blank():
    assert_xml_safe("mqtt_topic", "Acme/Line\tSpeed\n\r")
    assert_xml_safe("mqtt_topic", "")


def test_tag_spec_rejects_illegal_xml_control_char_in_topic():
    spec = ConnectivityTagSpec("%ID103", "", "Speed", "Acme/Line\x01Speed")
    with pytest.raises(ValueError, match="control character"):
        spec.validate()


def test_tag_spec_rejects_illegal_xml_control_char_in_display_name():
    spec = ConnectivityTagSpec("%ID103", "", "Speed\x02", "Acme/Line/Speed")
    with pytest.raises(ValueError, match="control character"):
        spec.validate()


def test_tag_spec_rejects_illegal_xml_control_char_in_node_id():
    spec = ConnectivityTagSpec("%ID\x03103", "", "Speed", "Acme/Line/Speed")
    with pytest.raises(ValueError, match="control character"):
        spec.validate()


def test_tag_spec_accepts_ordinary_text():
    spec = ConnectivityTagSpec("%ID103", "", "Speed", "Acme/Line/Speed")
    spec.validate()


def test_assert_unique_mqtt_topic_rejects_when_topic_is_already_subscribed():
    with pytest.raises(ValueError, match="mqtt_topic"):
        assert_unique_mqtt_topic({"Plant/A"}, "Plant/A", node_id="%ID2")


def test_assert_unique_mqtt_topic_allows_a_distinct_or_blank_topic():
    """Neither call raises: a distinct topic is fine, and a blank one is not yet assigned."""
    assert_unique_mqtt_topic({"Plant/A"}, "Plant/B", node_id="%ID2")
    assert_unique_mqtt_topic({"Plant/A"}, "", node_id="%ID2")


class _TopicRowsSession:
    """Fakes just enough of AsyncSession for `subscribed_topics`: one `execute().all()`."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._rows = rows

    async def execute(self, statement: object) -> _TopicRowsSession:  # noqa: ARG002
        return self

    def all(self) -> list[tuple[str, str, str]]:
        return self._rows


@pytest.mark.asyncio
async def test_subscribed_topics_excludes_the_given_server_and_node():
    session = _TopicRowsSession(
        [("srv_s7", "%ID1", "Plant/A"), ("srv_s7", "%ID2", "Plant/B"), ("srv_s7", "%ID3", "")]
    )
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    topics = await repo.subscribed_topics(session, exclude=("srv_s7", "%ID1"))
    assert topics == {"Plant/B"}


@pytest.mark.asyncio
async def test_subscribed_topics_with_no_exclusion_returns_every_topic():
    session = _TopicRowsSession([("srv_s7", "%ID1", "Plant/A"), ("srv_s7", "%ID2", "Plant/B")])
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    assert await repo.subscribed_topics(session) == {"Plant/A", "Plant/B"}


def test_replace_subscribed_tags_on_conflict_omits_display_name_and_context():
    source = inspect.getsource(ConnectivityRepository.replace_subscribed_tags)
    conflict_block = source.split("on_conflict_set = {", 1)[1].split("}", 1)[0]
    assert "browse_path" in conflict_block
    assert "subscribed" in conflict_block
    assert "updated_at" in conflict_block
    for column in (
        "display_name",
        "mqtt_topic",
        "asset_id",
        "unit_of_measure",
        "semantic_class",
        "data_type",
        "labels",
    ):
        assert column not in conflict_block, f"{column} must not be updated on rediscovery"


@pytest.mark.asyncio
async def test_replace_subscribed_tags_calls_after_flush():
    session = _FakeSession(tag=[], protocol="opc_ua")
    repo = ConnectivityRepository(_FakeDatabase(session))
    sentinel = object()
    calls: list[object] = []

    async def fake_sync_edge(self, session_arg, after_flush):  # noqa: ARG001
        calls.append(after_flush)

    with patch.object(ConnectivityRepository, "_sync_edge", fake_sync_edge):
        await repo.replace_subscribed_tags(
            "srv_opc",
            [ConnectivityTagSpec("ns=1;i=1", "Server/A", "A", "Server/A")],
            after_flush=sentinel,
        )

    assert calls == [sentinel]


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value

    def scalars(self) -> list[object]:
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]

    def all(self) -> list[object]:
        return self._value if isinstance(self._value, list) else []


class _FakeSession:
    def __init__(
        self,
        *,
        tag: object | None = None,
        asset_path: str | None = None,
        topic_rows: list[tuple[str, str, str]] | None = None,
        protocol: str | None = None,
        mqtt_topic: str | None = None,
    ) -> None:
        self.tag = tag
        self.asset_path = asset_path
        self.topic_rows = topic_rows or []
        self.protocol = protocol
        self.mqtt_topic = mqtt_topic
        self.statements: list[object] = []
        self.update_values: dict[str, object] | None = None

    async def execute(self, stmt: object) -> _ScalarResult:
        self.statements.append(stmt)
        if isinstance(stmt, Update):
            self.update_values = {
                column.key: getattr(value, "value", value) for column, value in stmt._values.items()
            }
            return _ScalarResult(None)
        if isinstance(stmt, Insert):
            return _ScalarResult(None)
        selected = [column.key for column in stmt.selected_columns]
        if selected == ["path"] or (len(selected) == 1 and selected[0] == "path"):
            return _ScalarResult(self.asset_path)
        if selected == ["server_id", "node_id", "mqtt_topic"]:
            return _ScalarResult(self.topic_rows)
        if selected == ["protocol"]:
            return _ScalarResult(self.protocol)
        if selected == ["mqtt_topic"]:
            return _ScalarResult(self.mqtt_topic if self.mqtt_topic is not None else getattr(self.tag, "mqtt_topic", None))
        return _ScalarResult(self.tag)


class _FakeDatabase:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


def _loader_blob(statement: object) -> str:
    """Loader options are not in compiled SQL; inspect `_with_options` instead."""
    chunks = [repr(getattr(statement, "_with_options", ()))]
    for opt in getattr(statement, "_with_options", ()):
        chunks.append(str(getattr(opt, "path", "")))
        chunks.append(repr(getattr(opt, "context", {})))
        chunks.append(str(opt))
        chunks.append(repr(opt))
    return " ".join(chunks).lower()


def _selects(session: _FakeSession) -> list[Select]:
    return [stmt for stmt in session.statements if isinstance(stmt, Select)]


@pytest.mark.asyncio
async def test_save_unit_of_measure_rejects_blank_symbol():
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await repo.save_unit_of_measure("")
    with pytest.raises(ValueError):
        await repo.save_unit_of_measure("   ")


@pytest.mark.asyncio
async def test_save_signal_label_rejects_blank_name():
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await repo.save_signal_label("")
    with pytest.raises(ValueError):
        await repo.save_signal_label("   ")


@pytest.mark.asyncio
async def test_save_unit_of_measure_trims_and_does_not_update_on_conflict():
    stored = SimpleNamespace(symbol="NTU", name="turbidity")
    session = _FakeSession(tag=stored)
    repo = ConnectivityRepository(_FakeDatabase(session))
    result = await repo.save_unit_of_measure("  NTU  ", "turbidity")
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled).upper()
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql
    assert compiled.params["symbol"] == "NTU"
    assert result is stored


@pytest.mark.asyncio
async def test_save_signal_label_trims_and_does_not_update_on_conflict():
    stored = SimpleNamespace(name="Cycle")
    session = _FakeSession(tag=stored)
    repo = ConnectivityRepository(_FakeDatabase(session))
    result = await repo.save_signal_label("  Cycle  ")
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled).upper()
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql
    assert compiled.params["name"] == "Cycle"
    assert result is stored


@pytest.mark.asyncio
async def test_list_units_of_measure_orders_by_symbol():
    session = _FakeSession(tag=[])
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.list_units_of_measure()
    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ORDER BY" in compiled.upper()
    assert "symbol" in compiled


@pytest.mark.asyncio
async def test_list_signal_labels_orders_by_name():
    session = _FakeSession(tag=[])
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.list_signal_labels()
    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ORDER BY" in compiled.upper()
    assert "name" in compiled


@pytest.mark.asyncio
async def test_update_tag_rejects_unknown_fields():
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="subscribed"):
        await repo.update_tag("s1", "ns=3;s=A", subscribed=False)


@pytest.mark.asyncio
async def test_update_tag_writes_only_fields_that_were_passed():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag)
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/T101/Level")
    assert session.update_values is not None
    assert set(session.update_values) == {"mqtt_topic", "updated_at"}
    assert session.update_values["mqtt_topic"] == "Plant/T101/Level"


@pytest.mark.asyncio
async def test_update_tag_none_clears_unit_asset_class_and_type():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag)
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.update_tag(
        "s1",
        "ns=3;s=A",
        asset_id=None,
        unit_of_measure=None,
        semantic_class=None,
        data_type=None,
    )
    assert session.update_values is not None
    assert session.update_values["asset_id"] is None
    assert session.update_values["unit_of_measure"] is None
    assert session.update_values["semantic_class"] is None
    assert session.update_values["data_type"] is None


@pytest.mark.asyncio
async def test_update_tag_rejects_a_topic_already_subscribed_by_another_tag():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag, topic_rows=[("s1", "ns=3;s=B", "Plant/Taken")])
    repo = ConnectivityRepository(_FakeDatabase(session))
    with pytest.raises(ValueError, match="mqtt_topic"):
        await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/Taken")
    assert session.update_values is None


@pytest.mark.asyncio
async def test_update_tag_allows_a_distinct_topic():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag, topic_rows=[("s1", "ns=3;s=B", "Plant/Taken")])
    repo = ConnectivityRepository(_FakeDatabase(session))
    result = await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/New")
    assert result is tag
    assert session.update_values["mqtt_topic"] == "Plant/New"


@pytest.mark.asyncio
async def test_update_tag_rejects_a_control_character_in_the_topic_before_touching_the_database():
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control character"):
        await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/A\x01")


@pytest.mark.asyncio
async def test_update_tag_calls_sync_edge_when_after_flush_is_given():
    """`after_flush` is optional on `update_tag`; when given, it must reach `_sync_edge`."""
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag)
    repo = ConnectivityRepository(_FakeDatabase(session))
    sentinel = object()
    calls: list[object] = []

    async def fake_sync_edge(self, session_arg, after_flush):  # noqa: ARG001
        calls.append(after_flush)

    with patch.object(ConnectivityRepository, "_sync_edge", fake_sync_edge):
        await repo.update_tag("s1", "ns=3;s=A", after_flush=sentinel, mqtt_topic="Plant/B")

    assert calls == [sentinel]


@pytest.mark.asyncio
async def test_update_tag_topic_rewrite_failure_skips_after_flush():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag, mqtt_topic="Plant/A")
    repo = ConnectivityRepository(_FakeDatabase(session))
    sync_calls: list[object] = []

    async def fake_sync_edge(self, session_arg, after_flush):  # noqa: ARG001
        sync_calls.append(after_flush)

    async def failing_rewrite(session_arg, old_topic, new_topic):  # noqa: ARG001
        raise RuntimeError("timescale down")

    with patch.object(ConnectivityRepository, "_sync_edge", fake_sync_edge):
        with pytest.raises(RuntimeError, match="timescale down"):
            await repo.update_tag_topic(
                "s1",
                "ns=3;s=A",
                "Plant/B",
                after_flush=object(),
                on_topic_rewrite=failing_rewrite,
            )

    assert sync_calls == []


@pytest.mark.asyncio
async def test_update_tag_topic_rewrite_success_runs_before_after_flush():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag, mqtt_topic="Plant/A")
    repo = ConnectivityRepository(_FakeDatabase(session))
    order: list[str] = []
    sentinel = object()

    async def fake_sync_edge(self, session_arg, after_flush):  # noqa: ARG001
        order.append("sync")

    async def rewrite(session_arg, old_topic, new_topic):
        order.append(f"rewrite:{old_topic}->{new_topic}")

    with patch.object(ConnectivityRepository, "_sync_edge", fake_sync_edge):
        await repo.update_tag_topic(
            "s1",
            "ns=3;s=A",
            "Plant/B",
            after_flush=sentinel,
            on_topic_rewrite=rewrite,
        )

    assert order == ["rewrite:Plant/A->Plant/B", "sync"]


@pytest.mark.asyncio
async def test_update_tag_topic_forwards_after_flush_and_mqtt_topic_to_update_tag():
    """`updateConnectivityTagTopic` must regenerate Edge XML, same as `updateConnectivityTag`."""
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    sentinel = object()
    with patch.object(ConnectivityRepository, "update_tag", new=AsyncMock(return_value="stored")) as mocked:
        result = await repo.update_tag_topic("s1", "ns=3;s=A", "Plant/B", after_flush=sentinel)
    assert result == "stored"
    mocked.assert_awaited_once_with(
        "s1", "ns=3;s=A", after_flush=sentinel, on_topic_rewrite=None, mqtt_topic="Plant/B"
    )


@pytest.mark.asyncio
async def test_update_tag_topic_without_after_flush_still_works():
    repo = ConnectivityRepository(database=None)  # type: ignore[arg-type]
    with patch.object(ConnectivityRepository, "update_tag", new=AsyncMock(return_value="stored")) as mocked:
        result = await repo.update_tag_topic("s1", "ns=3;s=A", "Plant/B")
    assert result == "stored"
    mocked.assert_awaited_once_with(
        "s1", "ns=3;s=A", after_flush=None, on_topic_rewrite=None, mqtt_topic="Plant/B"
    )


@pytest.mark.asyncio
async def test_update_tag_upserts_metric_when_asset_and_unit_are_set():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="AcmeWater/Site1/Furnace/Heater/Temp",
        asset_id=42,
        unit_of_measure="°C",
    )
    session = _FakeSession(tag=tag, asset_path="AcmeWater/Site1/Furnace")
    repo = ConnectivityRepository(_FakeDatabase(session))
    captured: dict[str, object] = {}

    async def fake_define_metric(self, metric_key, **kwargs):  # noqa: ARG001
        captured["metric_key"] = metric_key
        captured.update(kwargs)
        return SimpleNamespace()

    with patch("uns_model.connectivity.AssetModelRepository.define_metric", fake_define_metric):
        result = await repo.update_tag("s1", "ns=3;s=A", display_name="Temp")

    assert result is tag
    assert captured["metric_key"] == "Heater/Temp"
    assert captured["asset_path"] == "AcmeWater/Site1/Furnace"
    assert captured["unit_of_measure"] == "°C"
    assert captured["display_name"] == "Temp"


@pytest.mark.asyncio
async def test_list_subscribed_tags_eager_loads_asset():
    session = _FakeSession(tag=[])
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.list_subscribed_tags("s1")
    blob = _loader_blob(session.statements[0])
    assert "asset" in blob


@pytest.mark.asyncio
async def test_list_servers_eager_loads_tag_assets():
    session = _FakeSession(tag=[])
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.list_servers()
    blob = _loader_blob(session.statements[0])
    assert "tags" in blob
    assert "asset" in blob


@pytest.mark.asyncio
async def test_update_tag_eager_loads_asset_on_returned_row():
    tag = SimpleNamespace(
        server_id="s1",
        node_id="ns=3;s=A",
        browse_path="Heater/Temp",
        display_name="Temp",
        mqtt_topic="Plant/A",
        asset_id=None,
        unit_of_measure=None,
    )
    session = _FakeSession(tag=tag, mqtt_topic="Plant/A")
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/T101/Level")
    # old topic, subscribed_topics check, then tag read with asset eager load.
    blob = _loader_blob(_selects(session)[2])
    assert "asset" in blob
