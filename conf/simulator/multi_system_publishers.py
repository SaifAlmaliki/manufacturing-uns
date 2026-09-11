#!/usr/bin/env python3
"""Halabja multi-system MQTT publishers for UNS-to-lake end-to-end qualification.

Publishes machine telemetry (raw), MES production orders (raw), LIMS lab results
(uns-publication-v1), and SAP material documents (uns-publication-v1) on topics
registered in conf/settings.yaml publication_routes.

Host (stack running):
  uv run python conf/simulator/multi_system_publishers.py

In Docker:
  npm run sim:multi-system:stack
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import signal
import sys
import time
import uuid
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

DEFAULT_ENTERPRISE = "HalabjaWTP"
DEFAULT_SITE = "Halabja"
DEFAULT_SITE_ID = "halabja"
DEFAULT_BOOT_ID = "halabja-sim-boot"
DEFAULT_INTERVAL_SECONDS = 15.0

MACHINE_TOPICS = (
    "Distribution/Train1/FT201/Value",
    "Distribution/Train1/PT201/Value",
    "Treatment/Train1/B101/Value",
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _iso_z(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_publication_wrapper(
    *,
    source_application: str,
    site_id: str,
    payload_schema_id: str,
    payload_schema_version: str,
    original_payload: bytes,
    source_boot_id: str,
    source_sequence: int,
    content_type: str = "application/json",
    occurred_at: datetime | None = None,
) -> bytes:
    instant = occurred_at or _utc_now()
    wire = {
        "publication_version": 1,
        "source_application": source_application,
        "site_id": site_id,
        "payload_schema_id": payload_schema_id,
        "payload_schema_version": payload_schema_version,
        "content_type": content_type,
        "original_payload_base64": base64.b64encode(original_payload).decode("ascii"),
        "occurred_at": _iso_z(instant),
        "source_boot_id": source_boot_id,
        "source_sequence": source_sequence,
    }
    return json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _machine_payload(sequence: int) -> bytes:
    timestamp_ms = int(_utc_now().timestamp() * 1000)
    body = {
        "value": round(18.0 + random.uniform(-2.0, 2.0), 2),
        "timestamp": timestamp_ms,
        "sequence": sequence,
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _mes_payload(sequence: int) -> bytes:
    body = {
        "order_id": f"PO-{10000 + sequence}",
        "material": random.choice(("PART-A", "PART-B", "CHEM-9")),
        "quantity": random.randint(50, 500),
        "uom": "EA",
        "status": random.choice(("RELEASED", "IN_PROGRESS", "COMPLETED")),
        "planned_start": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _lims_payload(sequence: int) -> bytes:
    body = {
        "sample_id": f"S-{2000 + sequence}",
        "parameter": "turbidity",
        "result": round(random.uniform(0.5, 6.0), 2),
        "unit": "NTU",
        "status": random.choice(("PASS", "HOLD", "FAIL")),
        "collected_at": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _sap_payload(sequence: int) -> bytes:
    body = {
        "material_document": f"4900{100000 + sequence}",
        "movement_type": random.choice(("261", "262", "101")),
        "material": random.choice(("RAW-100", "CHEM-9", "PART-A")),
        "quantity": random.randint(-120, 120),
        "uom": "KG",
        "plant": "HALB",
        "storage_location": random.choice(("WH01", "LINE1", "QC-LAB")),
        "posted_at": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


class MultiSystemPublisher:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        enterprise: str,
        site: str,
        site_id: str,
        boot_id: str,
        interval_seconds: float,
    ) -> None:
        self._prefix = f"{enterprise}/{site}"
        self._site_id = site_id
        self._boot_id = boot_id
        self._interval_seconds = interval_seconds
        self._sequence = 0
        self._running = True
        client_id = f"uns_multi_system_sim_{uuid.uuid4().hex[:8]}"
        self._host = host
        self._port = port
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.connect(host, port, keepalive=30)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None = None,
    ) -> None:
        if reason_code.is_failure:
            raise RuntimeError(f"MQTT connect failed: {reason_code}")

    def stop(self) -> None:
        self._running = False

    def _publish(self, topic: str, payload: bytes) -> None:
        info = self._client.publish(topic, payload, qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed for {topic}: rc={info.rc}")

    def publish_once(self) -> None:
        self._sequence += 1
        seq = self._sequence

        machine_topic = MACHINE_TOPICS[(seq - 1) % len(MACHINE_TOPICS)]
        self._publish(f"{self._prefix}/{machine_topic}", _machine_payload(seq))

        self._publish(f"{self._prefix}/MES/orders", _mes_payload(seq))

        lims_body = _lims_payload(seq)
        self._publish(
            f"{self._prefix}/LIMS/results",
            build_publication_wrapper(
                source_application="lims",
                site_id=self._site_id,
                payload_schema_id="lab-result",
                payload_schema_version="1",
                original_payload=lims_body,
                source_boot_id=self._boot_id,
                source_sequence=seq,
            ),
        )

        sap_body = _sap_payload(seq)
        self._publish(
            f"{self._prefix}/SAP/material-documents",
            build_publication_wrapper(
                source_application="sap",
                site_id=self._site_id,
                payload_schema_id="material-document",
                payload_schema_version="1",
                original_payload=sap_body,
                source_boot_id=self._boot_id,
                source_sequence=seq,
            ),
        )

        print(
            f"[{_iso_z(_utc_now())}] published cycle {seq}: "
            f"machine + MES + LIMS + SAP under {self._prefix}/",
            flush=True,
        )

    def run(self) -> None:
        print(
            f"Multi-system simulator -> {self._host}:{self._port} "
            f"every {self._interval_seconds}s (Ctrl+C to stop)",
            flush=True,
        )
        while self._running:
            self.publish_once()
            self._client.loop(timeout=0.2)
            deadline = time.monotonic() + self._interval_seconds
            while self._running and time.monotonic() < deadline:
                self._client.loop(timeout=0.2)
                time.sleep(0.1)
        self._client.disconnect()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=_env("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(_env("MQTT_PORT", "1883")))
    parser.add_argument("--enterprise", default=_env("ENTERPRISE", DEFAULT_ENTERPRISE))
    parser.add_argument("--site", default=_env("SITE", DEFAULT_SITE))
    parser.add_argument("--site-id", default=_env("SITE_ID", DEFAULT_SITE_ID))
    parser.add_argument("--boot-id", default=_env("BOOT_ID", DEFAULT_BOOT_ID))
    parser.add_argument(
        "--interval",
        type=float,
        default=float(_env("INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))),
    )
    parser.add_argument("--once", action="store_true", help="Publish one cycle and exit")
    args = parser.parse_args(argv)

    publisher = MultiSystemPublisher(
        host=args.host,
        port=args.port,
        enterprise=args.enterprise,
        site=args.site,
        site_id=args.site_id,
        boot_id=args.boot_id,
        interval_seconds=args.interval,
    )

    def _handle_signal(_signum: int, _frame: object) -> None:
        publisher.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.once:
        publisher.publish_once()
        publisher._client.loop(timeout=1.0)
        publisher._client.disconnect()
        return 0

    publisher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
