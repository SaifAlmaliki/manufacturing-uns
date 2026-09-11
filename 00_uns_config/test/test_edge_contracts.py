"""Contract tests for pure edge desired-state documents."""

from __future__ import annotations

import json

import pytest

from uns_config.edge_config_digest import configuration_digest
from uns_config.edge_contracts import (
    AdapterConfig,
    EdgeConfig,
    EdgeConfigError,
    EdgeReport,
    decode_edge_config,
    validate_collection_only,
)

MAX_EDGE_CONFIG_BYTES = 4 * 1024 * 1024


def _minimal_document(**overrides) -> dict:
    base = {
        "contract_version": 1,
        "edge_id": "edge-01",
        "revision": 1,
        "adapters": [],
        "required_route_revision": 1,
        "secret_refs": [],
        "deleted_adapter_ids": [],
    }
    base.update(overrides)
    base["digest"] = configuration_digest(base)
    return base


def _opc_ua_adapter(**overrides) -> dict:
    tags = overrides.pop(
        "tags",
        [
            {
                "tag_id": "temperature",
                "node_id": "ns=2;s=Temperature",
                "data_type": "Double",
            }
        ],
    )
    connection = {
        "uri": "opc.tcp://opcua-simulator:4840/uns-sim/",
        "security_mode": "None",
        "security_policy": "None",
        "read_only": True,
    }
    connection.update(overrides)
    return {
        "adapter_id": "catalog-opcua-sim",
        "protocol": "opc_ua",
        "connection": connection,
        "tags": tags,
        "northbound_mappings": [
            {
                "tag_id": "temperature",
                "topic": "plant-01/machines/edge-01/opcua/temperature",
            }
        ],
    }


def _modbus_adapter(**overrides) -> dict:
    tags = overrides.pop(
        "tags",
        [
            {
                "tag_id": "temperature",
                "address": 0,
                "function": "holding_register",
                "data_type": "UInt16",
            }
        ],
    )
    connection = {
        "host": "modbus-simulator",
        "port": 1502,
        "unit_id": 1,
        "read_only": True,
    }
    connection.update(overrides)
    return {
        "adapter_id": "catalog-modbus-sim",
        "protocol": "modbus",
        "connection": connection,
        "tags": tags,
        "northbound_mappings": [
            {
                "tag_id": "temperature",
                "topic": "plant-01/machines/edge-01/modbus/temperature",
            }
        ],
    }


def _s7_adapter() -> dict:
    return {
        "adapter_id": "catalog-fixture-s7",
        "protocol": "s7",
        "connection": {
            "host": "192.0.2.1",
            "port": 102,
            "controller_type": "S7_1500",
            "read_only": True,
        },
        "tags": [
            {
                "tag_id": "speed",
                "address": "%ID103",
                "data_type": "Integer",
            }
        ],
        "northbound_mappings": [
            {
                "tag_id": "speed",
                "topic": "Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed",
            }
        ],
    }


def _ethernet_ip_adapter() -> dict:
    return {
        "adapter_id": "catalog-fixture-eip",
        "protocol": "ethernet_ip",
        "connection": {
            "host": "192.0.2.2",
            "port": 44818,
            "read_only": True,
        },
        "tags": [
            {
                "tag_id": "pressure",
                "address": "Program:MainProgram.Pressure",
                "data_type": "Double",
            }
        ],
        "northbound_mappings": [
            {
                "tag_id": "pressure",
                "topic": "Acme/Test/Area/Line/Cell/EIP/ProcessValue/Pressure",
            }
        ],
    }


@pytest.mark.parametrize(
    "adapter_factory",
    [_opc_ua_adapter, _modbus_adapter, _s7_adapter, _ethernet_ip_adapter],
)
def test_round_trip_first_release_protocol_fixtures(adapter_factory):
    document = _minimal_document(adapters=[adapter_factory()])
    restored = decode_edge_config(json.dumps(document).encode("utf-8"))
    assert restored.edge_id == "edge-01"
    assert restored.revision == 1
    assert len(restored.adapters) == 1
    assert restored.adapters[0].protocol == adapter_factory()["protocol"]
    assert restored.digest == document["digest"]


def test_secret_values_cannot_appear_in_public_desired_state():
    document = _minimal_document(
        adapters=[_opc_ua_adapter()],
        secret_refs=[{"secret_id": "catalog-opcua-sim/password", "version": 1}],
    )
    wire = json.dumps(document)
    assert "supersecret" not in wire
    assert '"password"' not in wire
    restored = decode_edge_config(wire.encode("utf-8"))
    assert restored.secret_refs == ({"secret_id": "catalog-opcua-sim/password", "version": 1},)


def test_decode_rejects_inline_secret_values_in_connection():
    document = _minimal_document(
        adapters=[_opc_ua_adapter(password="supersecret")],
    )
    with pytest.raises(EdgeConfigError, match="secret_value_forbidden"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_decode_rejects_unknown_contract_version():
    document = _minimal_document(contract_version=99)
    with pytest.raises(EdgeConfigError, match="unsupported_contract"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_decode_rejects_missing_edge_id():
    document = _minimal_document()
    del document["edge_id"]
    document["digest"] = configuration_digest(document)
    with pytest.raises(EdgeConfigError, match="missing_field"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_decode_rejects_boolean_revision():
    document = _minimal_document(revision=True)
    document["digest"] = configuration_digest(document)
    with pytest.raises(EdgeConfigError, match="invalid_field"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_decode_rejects_duplicate_json_keys():
    raw = (
        b'{"contract_version":1,"edge_id":"edge-01","edge_id":"edge-02",'
        b'"revision":1,"adapters":[],"required_route_revision":1,'
        b'"secret_refs":[],"deleted_adapter_ids":[],"digest":"deadbeef"}'
    )
    with pytest.raises(EdgeConfigError, match="duplicate_key"):
        decode_edge_config(raw)


def test_decode_rejects_nan_values():
    raw = (
        b'{"contract_version":1,"edge_id":"edge-01","revision":NaN,'
        b'"adapters":[],"required_route_revision":1,'
        b'"secret_refs":[],"deleted_adapter_ids":[],"digest":"deadbeef"}'
    )
    with pytest.raises(EdgeConfigError, match="invalid_nan"):
        decode_edge_config(raw)


def test_decode_rejects_oversized_raw_document():
    padding = "x" * (MAX_EDGE_CONFIG_BYTES - 128)
    document = _minimal_document(padding=padding)
    raw = json.dumps(document).encode("utf-8")
    assert len(raw) > MAX_EDGE_CONFIG_BYTES
    with pytest.raises(EdgeConfigError, match="oversize"):
        decode_edge_config(raw)


def test_decode_rejects_excessive_adapter_count_before_building_adapters():
    adapters = [
        {
            "adapter_id": f"catalog-{index}",
            "protocol": "modbus",
            "connection": {"host": "h", "port": 1502, "unit_id": 1, "read_only": True},
            "tags": [],
            "northbound_mappings": [],
        }
        for index in range(501)
    ]
    document = _minimal_document(adapters=adapters)
    with pytest.raises(EdgeConfigError, match="too_many_adapters"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_decode_rejects_excessive_tag_count_before_building_tags():
    tags = [
        {
            "tag_id": f"tag-{index}",
            "address": index,
            "function": "holding_register",
            "data_type": "UInt16",
        }
        for index in range(20_001)
    ]
    document = _minimal_document(adapters=[_modbus_adapter(tags=tags)])
    with pytest.raises(EdgeConfigError, match="too_many_tags"):
        decode_edge_config(json.dumps(document).encode("utf-8"))


def test_validate_collection_only_rejects_southbound_mappings():
    config = decode_edge_config(
        json.dumps(
            _minimal_document(
                adapters=[
                    {
                        **_modbus_adapter(),
                        "southbound_mappings": [{"topic": "cmd/topic", "tag_id": "temperature"}],
                    }
                ]
            )
        ).encode("utf-8")
    )
    with pytest.raises(EdgeConfigError, match="southbound_forbidden"):
        validate_collection_only(config)


def test_validate_collection_only_rejects_write_enabled_protocol_settings():
    config = decode_edge_config(
        json.dumps(_minimal_document(adapters=[_modbus_adapter(read_only=False)])).encode("utf-8")
    )
    with pytest.raises(EdgeConfigError, match="writes_forbidden"):
        validate_collection_only(config)


def test_validate_collection_only_rejects_undeclared_deletion_targets():
    config = decode_edge_config(
        json.dumps(
            _minimal_document(deleted_adapter_ids=["simulation"])
        ).encode("utf-8")
    )
    with pytest.raises(EdgeConfigError, match="undeclared_deletion"):
        validate_collection_only(config)


def test_validate_collection_only_rejects_adapter_marked_for_deletion():
    adapter = _modbus_adapter()
    config = decode_edge_config(
        json.dumps(
            _minimal_document(
                adapters=[adapter],
                deleted_adapter_ids=[adapter["adapter_id"]],
            )
        ).encode("utf-8")
    )
    with pytest.raises(EdgeConfigError, match="undeclared_deletion"):
        validate_collection_only(config)


def test_edge_report_dataclass_is_frozen():
    report = EdgeReport(
        edge_id="edge-01",
        boot_id="boot-1",
        report_sequence=1,
        desired_revision=2,
        applied_revision=2,
        applied_digest="abc",
        phase="applied",
        adapter_results=(),
        last_error_code=None,
        versions={"agent": "0.1.0"},
        capabilities={"protocols": ("modbus", "opc_ua")},
    )
    with pytest.raises(AttributeError):
        report.phase = "failed"


def test_adapter_config_dataclass_is_frozen():
    adapter = AdapterConfig(
        adapter_id="catalog-a",
        protocol="modbus",
        connection={"read_only": True},
        tags=(),
        northbound_mappings=(),
    )
    with pytest.raises(AttributeError):
        adapter.protocol = "opc_ua"
