"""Protocol collector stub: reads OPC UA / Modbus fixtures and publishes to local Edge MQTT."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

EDGE_HOST = os.environ.get("EDGE_MQTT_HOST", "hivemq-edge")
EDGE_PORT = int(os.environ.get("EDGE_MQTT_PORT", "1883"))
CLOUD_MANAGEMENT_HOST = os.environ.get("CLOUD_MANAGEMENT_HOST", "cloud-management")
CLOUD_MANAGEMENT_PORT = int(os.environ.get("CLOUD_MANAGEMENT_PORT", "443"))
EDGE_ID = os.environ.get("EDGE_ID", "edge-01")
CA_DIR = Path("/qualification-ca")
FIXTURES = Path(os.environ.get("FIXTURE_PROFILE_FILE", "/app/fixtures.json"))
PROFILE = os.environ.get("FIXTURE_PROFILE", "edge_simulation")
POLL_SECONDS = float(os.environ.get("PROTOCOL_POLL_SECONDS", "2"))


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(CA_DIR / "ca.crt"))


def _cloud_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"https://{CLOUD_MANAGEMENT_HOST}:{CLOUD_MANAGEMENT_PORT}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _fixture_manifest() -> dict[str, Any]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return data["profiles"][PROFILE]


def _applied_connections() -> list[tuple[int, dict[str, Any]]]:
    try:
        edge = _cloud_request("GET", f"/api/v1/edges/{EDGE_ID}")
    except urllib.error.HTTPError:
        return []
    applied: list[tuple[int, dict[str, Any]]] = []
    for revision, connection in edge.get("connections", {}).items():
        if connection.get("phase") == "applied":
            applied.append((int(revision), connection))
    return sorted(applied)


def _publish(topic: str, payload: bytes, client: mqtt.Client) -> None:
    info = client.publish(topic, payload, qos=1, retain=False)
    info.wait_for_publish(timeout=10.0)
    if not info.is_published():
        raise RuntimeError(f"protocol publish not acknowledged for {topic}")


def _read_opcua(settings: dict[str, Any]) -> dict[str, float]:
    import asyncio

    from asyncua import Client

    async def _read() -> dict[str, float]:
        client = Client(url=settings["endpoint"])
        await client.connect()
        values: dict[str, float] = {}
        for node in settings.get("nodes", []):
            handle = client.get_node(node["node_id"])
            values[node["name"]] = float(await handle.read_value())
        await client.disconnect()
        return values

    return asyncio.run(_read())


def _read_modbus(settings: dict[str, Any]) -> dict[str, float]:
    from pymodbus.client import ModbusTcpClient

    client = ModbusTcpClient(settings["host"], port=int(settings["port"]))
    client.connect()
    values: dict[str, float] = {}
    for register in settings.get("registers", []):
        response = client.read_holding_registers(
            address=int(register["address"]),
            count=1,
            device_id=int(settings.get("unit_id", 1)),
        )
        if response.isError():
            raise RuntimeError(f"modbus read failed for address {register['address']}")
        raw = int(response.registers[0])
        scale = int(register.get("scale", 1))
        values[register["name"]] = raw / scale
    client.close()
    return values


def _collect_revision(revision: int, connection: dict[str, Any], client: mqtt.Client) -> None:
    protocol = connection.get("protocol")
    settings = connection.get("settings", {})
    if protocol == "opc_ua":
        values = _read_opcua(settings)
        for node in settings.get("nodes", []):
            value = values[node["name"]]
            payload = json.dumps(
                {"value": value, "source_revision": revision, "node": node["name"]},
                separators=(",", ":"),
            ).encode("utf-8")
            _publish(node["topic"], payload, client)
    elif protocol == "modbus":
        values = _read_modbus(settings)
        for register in settings.get("registers", []):
            value = values[register["name"]]
            payload = json.dumps(
                {"value": value, "source_revision": revision, "register": register["name"]},
                separators=(",", ":"),
            ).encode("utf-8")
            _publish(register["topic"], payload, client)


def main() -> None:
    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="qualification-protocol-collector",
    )
    mqtt_client.connect(EDGE_HOST, EDGE_PORT, keepalive=30)
    mqtt_client.loop_start()
    seen: set[int] = set()
    while True:
        for revision, connection in _applied_connections():
            if revision in seen:
                continue
            _collect_revision(revision, connection, mqtt_client)
            seen.add(revision)
            print(
                json.dumps(
                    {
                        "protocol_collect": {
                            "revision": revision,
                            "protocol": connection.get("protocol"),
                        }
                    }
                ),
                flush=True,
            )
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
