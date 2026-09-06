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
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from uns_model.connectivity import (
    ConnectivityRepository,
    ConnectivityTagSpec,
    merge_discovered,
    metric_key_for_tag,
)
from uns_model.tables import (
    SEEDED_UNITS_OF_MEASURE,
    SIGNAL_DATA_TYPES,
    SIGNAL_SEMANTIC_CLASSES,
)


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


class _FakeSession:
    def __init__(self, *, tag: object | None = None, asset_path: str | None = None) -> None:
        self.tag = tag
        self.asset_path = asset_path
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
    session = _FakeSession(tag=tag)
    repo = ConnectivityRepository(_FakeDatabase(session))
    await repo.update_tag("s1", "ns=3;s=A", mqtt_topic="Plant/T101/Level")
    blob = _loader_blob(_selects(session)[0])
    assert "asset" in blob
