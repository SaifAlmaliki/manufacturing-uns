"""OPC UA test-server fixture for qualification and edge-simulation profiles."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from asyncua import Server, ua

FIXTURES = Path(__file__).with_name("fixtures.json")


def _profile_name() -> str:
    return os.environ.get("FIXTURE_PROFILE", "edge_simulation")


def _load_fixture() -> dict:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return data["profiles"][_profile_name()]["opcua"]


async def main() -> None:
    fixture = _load_fixture()
    server = Server()
    await server.init()
    server.set_endpoint(fixture["endpoint"])
    server.set_server_name(f"UNS {_profile_name()} OPC UA")
    namespace_idx = await server.register_namespace(fixture["namespace_uri"])
    objects = server.nodes.objects
    device = await objects.add_object(namespace_idx, "SimulationDevice")
    node_handles: dict[str, object] = {}
    for node in fixture["nodes"]:
        variable = await device.add_variable(
            ua.NodeId.from_string(node["node_id"]),
            node["name"],
            node["value"],
        )
        await variable.set_writable(False)
        node_handles[node["name"]] = variable

    schedule = fixture.get("schedule") or []

    async def _run_schedule() -> None:
        if not schedule:
            return
        while True:
            for step in schedule:
                for name, value in step.get("values", {}).items():
                    handle = node_handles.get(name)
                    if handle is not None:
                        await handle.write_value(value)
                await asyncio.sleep(float(step.get("hold_seconds", 60)))

    async with server:
        if schedule:
            asyncio.create_task(_run_schedule())
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
