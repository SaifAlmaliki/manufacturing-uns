"""Unit tests for OPC UA node -> UNS topic mapping."""

import pytest
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.tag_map import build_bindings, derive_topic, find_conflicts

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"


def _tag(node_id: str, metric_path: str, asset: str = ASSET) -> TagConfig:
    return TagConfig(node_id=node_id, asset=asset, metric_path=metric_path)


def _server(*tags: TagConfig) -> ServerConfig:
    return ServerConfig(name="plc01", url="opc.tcp://host:4840/", publishing_interval_ms=200, tags=tags)


@pytest.mark.parametrize(
    ("asset", "metric_path", "expected"),
    [
        (ASSET, "ProcessValue/Temperature", f"{ASSET}/ProcessValue/Temperature"),
        (ASSET, "", ASSET),
        ("/Ent/Site/", "/ProcessValue/Temperature/", "Ent/Site/ProcessValue/Temperature"),
    ],
)
def test_derive_topic(asset, metric_path, expected):
    assert derive_topic(asset, metric_path) == expected


def test_derive_topic_rejects_an_empty_asset():
    with pytest.raises(ValueError, match="asset"):
        derive_topic("", "ProcessValue/Temperature")


def test_build_bindings_carries_equipment_and_metric_key():
    bindings = build_bindings(_server(_tag("ns=2;i=5", "ProcessValue/Temperature")))
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.topic == f"{ASSET}/ProcessValue/Temperature"
    assert binding.equipment == "MixerTank"
    assert binding.server_name == "plc01"
    # A MetricDefinition is keyed by Metric Key, which includes the payload leaf.
    assert binding.metric_key == "ProcessValue/Temperature/value"


def test_metric_key_of_an_asset_level_tag_is_just_the_leaf():
    bindings = build_bindings(_server(TagConfig(node_id="ns=2;i=9", asset=ASSET, metric_path="")))
    assert bindings[0].metric_key == "value"


def test_build_bindings_preserves_unit_and_deadband():
    tag = TagConfig(
        node_id="ns=2;i=5",
        asset=ASSET,
        metric_path="ProcessValue/Temperature",
        unit="°C",
        deadband=Deadband(type="absolute", value=0.2),
    )
    binding = build_bindings(_server(tag))[0]
    assert binding.unit == "°C"
    assert binding.deadband == Deadband(type="absolute", value=0.2)


def test_find_conflicts_is_empty_for_a_clean_map():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=6", "ProcessValue/Pressure"))
    )
    assert find_conflicts(bindings) == []


def test_find_conflicts_reports_a_duplicate_node_id():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=5", "ProcessValue/Pressure"))
    )
    conflicts = find_conflicts(bindings)
    assert len(conflicts) == 1
    assert "ns=2;i=5" in conflicts[0]
    assert "duplicate node_id" in conflicts[0]


def test_find_conflicts_reports_two_tags_resolving_to_one_topic():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=6", "ProcessValue/Temperature"))
    )
    conflicts = find_conflicts(bindings)
    assert len(conflicts) == 1
    assert "duplicate topic" in conflicts[0]
    assert f"{ASSET}/ProcessValue/Temperature" in conflicts[0]


def test_find_conflicts_scopes_node_ids_per_server():
    """The same node_id on two different servers is normal, not a conflict."""
    plc01 = build_bindings(_server(_tag("ns=2;i=5", "ProcessValue/Temperature")))
    plc02 = build_bindings(
        ServerConfig(
            name="plc02",
            url="opc.tcp://other:4840/",
            publishing_interval_ms=200,
            tags=(_tag("ns=2;i=5", "ProcessValue/Temperature", asset="Ent/Site/Line2/Mixer"),),
        )
    )
    assert find_conflicts([*plc01, *plc02]) == []


def test_mqtt_topic_overrides_derive_topic():
    tag = TagConfig(
        node_id="ns=3;s=WTP_T101_Level",
        asset="ignored",
        metric_path="ignored",
        mqtt_topic="RawWater/T101/Level",
    )
    bindings = build_bindings(_server(tag))
    assert bindings[0].topic == "RawWater/T101/Level"
