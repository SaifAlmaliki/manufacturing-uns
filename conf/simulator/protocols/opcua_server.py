"""Minimal OPC UA qualification server for cloud-edge acceptance harness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from asyncua import Server, ua

FIXTURES = Path(__file__).with_name("fixtures.json")


def _load_fixture() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["opcua"]


async def main() -> None:
    fixture = _load_fixture()
    server = Server()
    await server.init()
    server.set_endpoint(fixture["endpoint"])
    server.set_server_name("UNS Cloud Edge Qualification OPC UA")
    namespace_idx = await server.register_namespace(fixture["namespace_uri"])
    objects = server.nodes.objects
    device = await objects.add_object(namespace_idx, "QualificationDevice")
    for node in fixture["nodes"]:
        variable = await device.add_variable(
            ua.NodeId.from_string(node["node_id"]),
            node["name"],
            node["value"],
        )
        await variable.set_writable(False)
    async with server:
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
