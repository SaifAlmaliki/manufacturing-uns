"""Modbus TCP test-server fixture for qualification and edge-simulation profiles."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import StartTcpServer

FIXTURES = Path(__file__).with_name("fixtures.json")


def _profile_name() -> str:
    return os.environ.get("FIXTURE_PROFILE", "edge_simulation")


def _load_fixture() -> dict:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return data["profiles"][_profile_name()]["modbus"]


def _values_from_fixture(fixture: dict) -> list[int]:
    values = [0] * 200
    convention = fixture.get("address_convention", "zero_based_holding_register")
    if "holding_registers" in fixture:
        for address, value in fixture["holding_registers"].items():
            index = int(address) - 40001
            if 0 <= index < len(values):
                values[index] = int(value)
        return values
    for address, meta in fixture.get("registers", {}).items():
        index = int(address) if convention == "zero_based_holding_register" else int(address) - 40001
        if 0 <= index < len(values):
            values[index] = int(meta["value"])
    return values


def _apply_schedule(context: ModbusServerContext, fixture: dict) -> None:
    schedule = fixture.get("schedule") or []
    if not schedule:
        return
    device = context._devices[0]
    holding_registers = device.simdevice.simdata[2][0].values
    while True:
        for step in schedule:
            for address, value in step.get("registers", {}).items():
                holding_registers[int(address)] = int(value)
            time.sleep(float(step.get("hold_seconds", 60)))


def _build_context(fixture: dict) -> ModbusServerContext:
    values = _values_from_fixture(fixture)
    store = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(1, values),
        ir=ModbusSequentialDataBlock(1, values),
    )
    return ModbusServerContext(devices=store, single=True)


def main() -> None:
    fixture = _load_fixture()
    context = _build_context(fixture)
    schedule = fixture.get("schedule") or []
    if schedule:
        threading.Thread(target=_apply_schedule, args=(context, fixture), daemon=True).start()
    StartTcpServer(
        context=context,
        address=(fixture["listen_host"], int(fixture["listen_port"])),
    )


if __name__ == "__main__":
    main()
