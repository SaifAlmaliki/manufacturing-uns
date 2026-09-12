"""Protocol fixture server contracts using real OPC UA and Modbus clients."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import pytest
from pymodbus.client import ModbusTcpClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "conf" / "simulator" / "protocols" / "fixtures.json"
OPCUA_SERVER = REPO_ROOT / "conf" / "simulator" / "protocols" / "opcua_server.py"
MODBUS_SERVER = REPO_ROOT / "conf" / "simulator" / "protocols" / "modbus_server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_profile_fixture(tmp_path: Path, profile: str, port: int, protocol: str) -> Path:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if protocol == "opcua":
        data["profiles"][profile]["opcua"]["endpoint"] = f"opc.tcp://127.0.0.1:{port}/uns-sim/"
    else:
        data["profiles"][profile]["modbus"]["listen_port"] = port
    fixture_file = tmp_path / f"fixtures-{protocol}-{port}.json"
    fixture_file.write_text(json.dumps(data), encoding="utf-8")
    return fixture_file


def _spawn_server(server_script: Path, fixture_file: Path, profile: str) -> threading.Thread:
    import os
    import runpy

    code = server_script.read_text(encoding="utf-8").replace(
        'FIXTURES = Path(__file__).with_name("fixtures.json")',
        f'FIXTURES = Path(r"{fixture_file.as_posix()}")',
    )
    temp_server = fixture_file.parent / f"run-{server_script.stem}.py"
    temp_server.write_text(code, encoding="utf-8")

    def _target() -> None:
        os.environ["FIXTURE_PROFILE"] = profile
        runpy.run_path(str(temp_server), run_name="__main__")

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"server did not listen on port {port}")


@pytest.fixture
def edge_simulation_fixture() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["profiles"]["edge_simulation"]


def test_fixture_manifest_documents_namespace_and_registers(edge_simulation_fixture):
    opcua = edge_simulation_fixture["opcua"]
    modbus = edge_simulation_fixture["modbus"]
    assert opcua["namespace_uri"] == "urn:uns:edge-simulation"
    assert opcua["endpoint"].endswith("/uns-sim/")
    names = {node["name"] for node in opcua["nodes"]}
    assert names == {"Temperature", "Pressure", "SampleCounter"}
    assert modbus["address_convention"] == "zero_based_holding_register"
    assert set(modbus["registers"]) == {"0", "1", "2"}


@pytest.mark.timeout(30)
def test_opcua_server_exposes_readable_string_nodes(edge_simulation_fixture, tmp_path: Path):
    from asyncua import Client

    port = _free_port()
    fixture_file = _write_profile_fixture(tmp_path, "edge_simulation", port, "opcua")
    _spawn_server(OPCUA_SERVER, fixture_file, "edge_simulation")
    _wait_for_port(port)

    async def _read() -> dict[str, float]:
        client = Client(url=f"opc.tcp://127.0.0.1:{port}/uns-sim/")
        await client.connect()
        values = {}
        for node in edge_simulation_fixture["opcua"]["nodes"]:
            handle = client.get_node(node["node_id"])
            values[node["name"]] = float(await handle.read_value())
        await client.disconnect()
        return values

    values = asyncio.run(_read())
    assert values["Temperature"] == 23.5
    assert values["Pressure"] == 1.15
    assert values["SampleCounter"] == 42


@pytest.mark.timeout(30)
def test_modbus_server_exposes_scaled_zero_based_registers(edge_simulation_fixture, tmp_path: Path):
    port = _free_port()
    fixture_file = _write_profile_fixture(tmp_path, "edge_simulation", port, "modbus")
    _spawn_server(MODBUS_SERVER, fixture_file, "edge_simulation")
    _wait_for_port(port)

    client = ModbusTcpClient("127.0.0.1", port=port)
    client.connect()
    temperature = client.read_holding_registers(0, count=1, device_id=1)
    pressure = client.read_holding_registers(1, count=1, device_id=1)
    counter = client.read_holding_registers(2, count=1, device_id=1)
    client.close()

    assert not temperature.isError()
    assert temperature.registers[0] / 10 == 23.5
    assert pressure.registers[0] / 100 == 1.15
    assert counter.registers[0] == 42
