"""Northbound MQTT bridge stub: hivemq-edge -> cloud-mqtt (simulator -> edge -> cloud)."""

from __future__ import annotations

import os
import signal
import sys
import time

import paho.mqtt.client as mqtt

EDGE_HOST = os.environ.get("EDGE_MQTT_HOST", "hivemq-edge")
EDGE_PORT = int(os.environ.get("EDGE_MQTT_PORT", "8883"))
CLOUD_HOST = os.environ.get("CLOUD_MQTT_HOST", "cloud-mqtt")
CLOUD_PORT = int(os.environ.get("CLOUD_MQTT_PORT", "1883"))
TOPIC_PREFIX = os.environ.get("EDGE_BRIDGE_TOPIC_PREFIX", "Enterprise/")


def main() -> None:
    cloud = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qualification-edge-bridge")
    connected = False

    def on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
        nonlocal connected
        connected = reason_code == 0
        if connected:
            client.subscribe(f"{TOPIC_PREFIX}#", qos=1)

    def on_message(client, userdata, message) -> None:  # noqa: ANN001
        cloud.publish(message.topic, payload=message.payload, qos=1)

    edge = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qualification-edge-bridge-edge")
    edge.on_connect = on_connect
    edge.on_message = on_message

    cloud.connect(CLOUD_HOST, CLOUD_PORT, keepalive=30)
    cloud.loop_start()
    edge.connect(EDGE_HOST, EDGE_PORT, keepalive=30)
    edge.loop_start()

    def shutdown(*_args: object) -> None:
        edge.loop_stop()
        cloud.loop_stop()
        edge.disconnect()
        cloud.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        if not connected:
            print("edge_bridge_waiting_for_edge_mqtt", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
