"""Protocol adapter compilation tests."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from uns_config.edge_contracts import AdapterConfig
from uns_edge_agent.protocols import CompileError, compile_adapter

EDGE_AGENT_SRC = Path(__file__).resolve().parents[1] / "src" / "uns_edge_agent"


def _opc_ua_adapter(**overrides) -> AdapterConfig:
    connection = {
        "uri": "opc.tcp://opcua-simulator:4840/uns-sim/",
        "security_mode": "None",
        "security_policy": "None",
        "read_only": True,
    }
    connection.update(overrides.pop("connection", {}))
    tags = overrides.pop(
        "tags",
        (
            {
                "tag_id": "temperature",
                "node_id": "ns=2;s=Temperature",
                "data_type": "Double",
            },
        ),
    )
    northbound_mappings = overrides.pop(
        "northbound_mappings",
        (
            {
                "tag_id": "temperature",
                "topic": "plant-01/machines/edge-01/opcua/temperature",
            },
        ),
    )
    return AdapterConfig(
        adapter_id=overrides.pop("adapter_id", "catalog-opcua-sim"),
        protocol="opc_ua",
        connection=connection,
        tags=tags,
        northbound_mappings=northbound_mappings,
    )


def _modbus_adapter(**overrides) -> AdapterConfig:
    connection = {
        "host": "modbus-simulator",
        "port": 1502,
        "unit_id": 1,
        "byte_order": "BIG_ENDIAN",
        "word_order": "BIG_ENDIAN",
        "polling_interval_ms": 1000,
        "read_only": True,
    }
    connection.update(overrides.pop("connection", {}))
    tags = overrides.pop(
        "tags",
        (
            {
                "tag_id": "temperature",
                "address": 0,
                "function": "holding_register",
                "data_type": "UInt16",
                "scale": 0.1,
            },
        ),
    )
    northbound_mappings = overrides.pop(
        "northbound_mappings",
        (
            {
                "tag_id": "temperature",
                "topic": "plant-01/machines/edge-01/modbus/temperature",
            },
        ),
    )
    return AdapterConfig(
        adapter_id=overrides.pop("adapter_id", "catalog-modbus-sim"),
        protocol="modbus",
        connection=connection,
        tags=tags,
        northbound_mappings=northbound_mappings,
    )


def _s7_adapter(**overrides) -> AdapterConfig:
    return AdapterConfig(
        adapter_id=overrides.pop("adapter_id", "catalog-fixture-s7"),
        protocol="s7",
        connection={
            "host": "192.0.2.1",
            "port": 102,
            "controller_type": "S7_1500",
            "read_only": True,
        },
        tags=(
            {
                "tag_id": "speed",
                "address": "%ID103",
                "data_type": "Integer",
            },
        ),
        northbound_mappings=(
            {
                "tag_id": "speed",
                "topic": "Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed",
            },
        ),
    )


def _eip_adapter(**overrides) -> AdapterConfig:
    return AdapterConfig(
        adapter_id=overrides.pop("adapter_id", "catalog-fixture-eip"),
        protocol="ethernet_ip",
        connection={
            "host": "192.0.2.2",
            "port": 44818,
            "read_only": True,
        },
        tags=(
            {
                "tag_id": "pressure",
                "address": "Program:MainProgram.Pressure",
                "data_type": "Double",
            },
        ),
        northbound_mappings=(
            {
                "tag_id": "pressure",
                "topic": "Acme/Test/Area/Line/Cell/EIP/ProcessValue/Pressure",
            },
        ),
    )


CAPABILITIES = {"version": 1, "protocols": ("opc_ua", "modbus", "s7", "ethernet_ip")}
ALLOWLIST = frozenset(
    {
        "opcua-simulator",
        "modbus-simulator",
        "192.0.2.1",
        "192.0.2.2",
        "10.0.0.5",
        "plant-plc.example",
    }
)


def test_opcua_fixture_compiles_endpoint_security_and_node_ids():
    compiled = compile_adapter(
        _opc_ua_adapter(),
        CAPABILITIES,
        {},
        endpoint_allowlist=ALLOWLIST,
    )
    assert compiled.adapter_body["config"]["uri"] == "opc.tcp://opcua-simulator:4840/uns-sim/"
    assert compiled.adapter_body["config"]["securityMode"] == "None"
    assert compiled.tags[0]["definition"]["node"] == "ns=2;s=Temperature"
    assert compiled.tags[0]["definition"]["dataType"] == "REAL"
    assert compiled.mappings[0]["topic"] == "plant-01/machines/edge-01/opcua/temperature"


def test_opcua_real_device_settings_preserve_owner_endpoint_and_security():
    adapter = _opc_ua_adapter(
        connection={
            "uri": "opc.tcp://plant-plc.example:4840/OPCUA/SimulationServer/",
            "security_mode": "SignAndEncrypt",
            "security_policy": "Basic256Sha256",
            "read_only": True,
        },
        tags=(
            {
                "tag_id": "motor_speed",
                "node_id": "ns=3;i=3001",
                "data_type": "Integer",
            },
        ),
        northbound_mappings=(
            {
                "tag_id": "motor_speed",
                "topic": "plant-01/machines/edge-01/opcua/motor_speed",
            },
        ),
    )
    compiled = compile_adapter(adapter, CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)
    assert compiled.adapter_body["config"]["uri"].startswith("opc.tcp://plant-plc.example:4840")
    assert compiled.adapter_body["config"]["securityMode"] == "SignAndEncrypt"
    assert compiled.tags[0]["definition"]["node"] == "ns=3;i=3001"


def test_modbus_fixture_compiles_host_unit_register_map_and_polling():
    compiled = compile_adapter(
        _modbus_adapter(),
        CAPABILITIES,
        {},
        endpoint_allowlist=ALLOWLIST,
    )
    config = compiled.adapter_body["config"]
    assert config["host"] == "modbus-simulator"
    assert config["port"] == 1502
    assert config["unitId"] == 1
    assert config["pollingIntervalMs"] == 1000
    definition = compiled.tags[0]["definition"]
    assert definition["address"] == 0
    assert definition["function"] == "HOLDING_REGISTER"
    assert definition["dataType"] == "UINT16"
    assert definition["scale"] == 0.1
    assert "node" not in definition


def test_modbus_real_device_settings_preserve_unit_id_and_register_map():
    adapter = _modbus_adapter(
        connection={
            "host": "10.0.0.5",
            "port": 1502,
            "unit_id": 7,
            "polling_interval_ms": 2500,
            "read_only": True,
        },
        tags=(
            {
                "tag_id": "level",
                "address": 42,
                "function": "input_register",
                "data_type": "Float32",
            },
        ),
        northbound_mappings=(
            {
                "tag_id": "level",
                "topic": "plant-01/machines/edge-01/modbus/level",
            },
        ),
    )
    compiled = compile_adapter(adapter, CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)
    assert compiled.adapter_body["config"]["unitId"] == 7
    assert compiled.tags[0]["definition"]["address"] == 42
    assert compiled.tags[0]["definition"]["function"] == "INPUT_REGISTER"


def test_s7_and_eip_compile_owner_addresses():
    s7 = compile_adapter(_s7_adapter(), CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)
    eip = compile_adapter(_eip_adapter(), CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)
    assert s7.tags[0]["definition"]["tagAddress"] == "%ID103"
    assert eip.tags[0]["definition"]["address"] == "Program:MainProgram.Pressure"


def test_rejects_endpoint_outside_allowlist():
    adapter = _modbus_adapter(connection={"host": "evil.example", "port": 1502, "unit_id": 1, "read_only": True})
    with pytest.raises(CompileError, match="endpoint_not_allowed"):
        compile_adapter(adapter, CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)


def test_rejects_southbound_mappings():
    adapter = AdapterConfig(
        adapter_id="catalog-modbus-sim",
        protocol="modbus",
        connection={"host": "modbus-simulator", "port": 1502, "unit_id": 1, "read_only": True},
        tags=(),
        northbound_mappings=(),
        southbound_mappings=({"topic": "cmd/topic", "tag_id": "temperature"},),
    )
    with pytest.raises(CompileError, match="southbound_forbidden"):
        compile_adapter(adapter, CAPABILITIES, {}, endpoint_allowlist=ALLOWLIST)


def test_rejects_unsupported_protocol_capability():
    adapter = _modbus_adapter()
    capabilities = {"version": 1, "protocols": ("opc_ua",)}
    with pytest.raises(CompileError, match="capability_missing"):
        compile_adapter(adapter, capabilities, {}, endpoint_allowlist=ALLOWLIST)


def test_rejects_invalid_secret_scope():
    adapter = _opc_ua_adapter()
    secrets = {"catalog-other/password": b"secret"}
    with pytest.raises(CompileError, match="secret_scope_invalid"):
        compile_adapter(adapter, CAPABILITIES, secrets, endpoint_allowlist=ALLOWLIST)


def test_production_modules_do_not_import_simulator_code():
    simulator_root = Path(__file__).resolve().parents[2] / "conf" / "simulator"
    for module_info in pkgutil.walk_packages([str(EDGE_AGENT_SRC)], prefix="uns_edge_agent."):
        module = importlib.import_module(module_info.name)
        module_path = Path(module.__file__).resolve()
        text = module_path.read_text(encoding="utf-8")
        assert "conf.simulator" not in text
        assert "conf\\simulator" not in text
        assert str(simulator_root) not in text
