"""Minimal Modbus TCP qualification server for cloud-edge acceptance harness."""

from __future__ import annotations

import json
from pathlib import Path

from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext

FIXTURES = Path(__file__).with_name("fixtures.json")


def _load_fixture() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["modbus"]


def _build_context(fixture: dict) -> ModbusServerContext:
    values = [0] * 200
    for address, value in fixture["holding_registers"].items():
        index = int(address) - 40001
        if 0 <= index < len(values):
            values[index] = int(value)
    store = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(0, values),
        ir=ModbusSequentialDataBlock(0, values),
    )
    return ModbusServerContext(devices=store, single=True)


def main() -> None:
    fixture = _load_fixture()
    StartTcpServer(
        context=_build_context(fixture),
        address=(fixture["listen_host"], int(fixture["listen_port"])),
    )


if __name__ == "__main__":
    main()
