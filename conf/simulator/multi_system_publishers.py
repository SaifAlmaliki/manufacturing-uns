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
import ssl
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import NamedTuple
from pathlib import Path

import paho.mqtt.client as mqtt

DEFAULT_ENTERPRISE = "HalabjaWTP"
DEFAULT_SITE = "Halabja"
DEFAULT_SITE_ID = "halabja"
DEFAULT_BOOT_ID = "halabja-sim-boot"
DEFAULT_INTERVAL_SECONDS = 15.0
DEFAULT_TOPIC_PREFIX = ""
IDENTITY_FILE = Path(os.environ.get("IDENTITY_FILE", "/tmp/uns_multi_system_identity.json"))

MACHINE_TOPICS = (
    "Distribution/Train1/FT201/Value",
    "Distribution/Train1/PT201/Value",
    "Treatment/Train1/B101/Value",
)

ACCEPTANCE_CASES = (
    {
        "machine_topic": "Distribution/Train1/FT201/Value",
        "machine_value": 18.42,
        "mes_order_id": "PO-10001",
        "lims_sample_id": "S-2001",
        "sap_document": "49001001001",
    },
    {
        "machine_topic": "Distribution/Train1/PT201/Value",
        "machine_value": 19.17,
        "mes_order_id": "PO-10002",
        "lims_sample_id": "S-2002",
        "sap_document": "49001001002",
    },
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


def _machine_payload(sequence: int, value: float | None = None) -> bytes:
    timestamp_ms = int(_utc_now().timestamp() * 1000)
    body = {
        "value": value if value is not None else round(18.0 + random.uniform(-2.0, 2.0), 2),
        "timestamp": timestamp_ms,
        "sequence": sequence,
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _mes_payload(sequence: int, order_id: str | None = None) -> bytes:
    body = {
        "order_id": order_id or f"PO-{10000 + sequence}",
        "material": random.choice(("PART-A", "PART-B", "CHEM-9")),
        "quantity": random.randint(50, 500),
        "uom": "EA",
        "status": random.choice(("RELEASED", "IN_PROGRESS", "COMPLETED")),
        "planned_start": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _lims_payload(sequence: int, sample_id: str | None = None) -> bytes:
    body = {
        "sample_id": sample_id or f"S-{2000 + sequence}",
        "parameter": "turbidity",
        "result": round(random.uniform(0.5, 6.0), 2),
        "unit": "NTU",
        "status": random.choice(("PASS", "HOLD", "FAIL")),
        "collected_at": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _sap_payload(sequence: int, material_document: str | None = None) -> bytes:
    body = {
        "material_document": material_document or f"4900{100000 + sequence}",
        "movement_type": random.choice(("261", "262", "101")),
        "material": random.choice(("RAW-100", "CHEM-9", "PART-A")),
        "quantity": random.randint(-120, 120),
        "uom": "KG",
        "plant": "HALB",
        "storage_location": random.choice(("WH01", "LINE1", "QC-LAB")),
        "posted_at": _iso_z(_utc_now()),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


class PublishResult(NamedTuple):
    topic: str
    admitted: bool
    acknowledged: bool
    reason: str | None = None


def _load_identity(path: Path, boot_id: str | None) -> tuple[str, int]:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("boot_id", boot_id or DEFAULT_BOOT_ID)), int(payload.get("sequence", 0))
    return boot_id or f"{DEFAULT_BOOT_ID}-{uuid.uuid4().hex[:8]}", 0


def _save_identity(path: Path, boot_id: str, sequence: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"boot_id": boot_id, "sequence": sequence}, separators=(",", ":")),
        encoding="utf-8",
    )


def _configure_tls(client: mqtt.Client, args: argparse.Namespace) -> None:
    if not args.tls:
        return
    context = ssl.create_default_context(cafile=args.ca_file)
    if args.tls_verify:
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    client.tls_set(
        ca_certs=args.ca_file,
        certfile=args.cert_file,
        keyfile=args.key_file,
        cert_reqs=context.verify_mode,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    if args.tls_verify and args.host:
        client.tls_insecure_set(False)


class MultiSystemPublisher:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        enterprise: str,
        site: str,
        site_id: str,
        boot_id: str | None,
        interval_seconds: float,
        topic_prefix: str,
        tls: bool,
        ca_file: str | None,
        cert_file: str | None,
        key_file: str | None,
        tls_verify: bool,
        username: str | None,
        password: str | None,
        acceptance_mode: bool,
        run_id: str | None,
        seed: int | None,
        case_count: int,
        malformed_mode: bool,
        identity_file: Path,
        client_id_prefix: str,
    ) -> None:
        self._prefix = topic_prefix or f"{enterprise}/{site}"
        self._site_id = site_id
        self._interval_seconds = interval_seconds
        self._acceptance_mode = acceptance_mode
        self._run_id = run_id
        self._seed = seed
        self._case_count = case_count
        self._malformed_mode = malformed_mode
        self._identity_file = identity_file
        self._boot_id, self._sequence = _load_identity(identity_file, boot_id)
        self._running = True
        self._host = host
        self._port = port
        self._manifest: list[dict[str, object]] = []
        client_id = f"{client_id_prefix}_{uuid.uuid4().hex[:8]}"
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        if username:
            self._client.username_pw_set(username, password)
        if tls:
            _configure_tls(
                self._client,
                argparse.Namespace(
                    tls=True,
                    ca_file=ca_file,
                    cert_file=cert_file,
                    key_file=key_file,
                    tls_verify=tls_verify,
                    host=host,
                ),
            )
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

    def publish_with_ack(self, topic: str, payload: bytes, *, qos: int = 1) -> PublishResult:
        info = self._client.publish(topic, payload, qos=qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return PublishResult(topic=topic, admitted=False, acknowledged=False, reason=f"rc={info.rc}")
        if qos == 0:
            return PublishResult(topic=topic, admitted=True, acknowledged=True)
        info.wait_for_publish(timeout=10.0)
        if info.is_published():
            return PublishResult(topic=topic, admitted=True, acknowledged=True)
        return PublishResult(topic=topic, admitted=True, acknowledged=False, reason="puback_timeout")

    def _publish(self, topic: str, payload: bytes) -> PublishResult:
        result = self.publish_with_ack(topic, payload)
        if not result.acknowledged and not self._malformed_mode:
            raise RuntimeError(f"MQTT publish not acknowledged for {topic}: {result.reason}")
        return result

    def publish_once(self, case_index: int | None = None) -> list[PublishResult]:
        self._sequence += 1
        seq = self._sequence
        results: list[PublishResult] = []
        case = None
        if self._acceptance_mode and case_index is not None:
            case = ACCEPTANCE_CASES[case_index % len(ACCEPTANCE_CASES)]

        machine_topic = (
            case["machine_topic"]
            if case
            else MACHINE_TOPICS[(seq - 1) % len(MACHINE_TOPICS)]
        )
        machine_value = case["machine_value"] if case else None
        machine_payload = _machine_payload(seq, machine_value)
        if self._malformed_mode:
            machine_payload = b"{not-json"
        results.append(
            self._publish(f"{self._prefix}/{machine_topic}", machine_payload)
        )

        mes_payload = _mes_payload(seq, case["mes_order_id"] if case else None)
        results.append(self._publish(f"{self._prefix}/MES/orders", mes_payload))

        lims_body = _lims_payload(seq, case["lims_sample_id"] if case else None)
        lims_wire = build_publication_wrapper(
            source_application="lims",
            site_id=self._site_id,
            payload_schema_id="lab-result",
            payload_schema_version="1",
            original_payload=lims_body,
            source_boot_id=self._boot_id,
            source_sequence=seq,
        )
        results.append(self._publish(f"{self._prefix}/LIMS/results", lims_wire))

        sap_body = _sap_payload(seq, case["sap_document"] if case else None)
        sap_wire = build_publication_wrapper(
            source_application="sap",
            site_id=self._site_id,
            payload_schema_id="material-document",
            payload_schema_version="1",
            original_payload=sap_body,
            source_boot_id=self._boot_id,
            source_sequence=seq,
        )
        results.append(self._publish(f"{self._prefix}/SAP/material-documents", sap_wire))

        _save_identity(self._identity_file, self._boot_id, self._sequence)
        self._manifest.append(
            {
                "run_id": self._run_id,
                "sequence": seq,
                "boot_id": self._boot_id,
                "topics": [result.topic for result in results],
                "acknowledged": all(result.acknowledged for result in results),
            }
        )
        print(
            f"[{_iso_z(_utc_now())}] published cycle {seq}: "
            f"machine + MES + LIMS + SAP under {self._prefix}/ "
            f"ack={all(result.acknowledged for result in results)}",
            flush=True,
        )
        return results

    def run(self) -> None:
        print(
            f"Multi-system simulator -> {self._host}:{self._port} "
            f"every {self._interval_seconds}s (Ctrl+C to stop)",
            flush=True,
        )
        if self._acceptance_mode:
            rng = random.Random(self._seed)
            cases = self._case_count or len(ACCEPTANCE_CASES)
            for index in range(cases):
                if not self._running:
                    break
                self.publish_once(case_index=rng.randint(0, len(ACCEPTANCE_CASES) - 1))
                self._client.loop(timeout=0.2)
            self._write_manifest()
            self._client.disconnect()
            return
        while self._running:
            self.publish_once()
            self._client.loop(timeout=0.2)
            deadline = time.monotonic() + self._interval_seconds
            while self._running and time.monotonic() < deadline:
                self._client.loop(timeout=0.2)
                time.sleep(0.1)
        self._client.disconnect()

    def _write_manifest(self) -> None:
        if not self._run_id:
            return
        manifest_path = Path(f"/tmp/uns_multi_system_manifest_{self._run_id}.json")
        manifest_path.write_text(json.dumps(self._manifest, indent=2), encoding="utf-8")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_secret_file(path: str | None) -> dict[str, str]:
    if not path or not Path(path).is_file():
        return {}
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=_env("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(_env("MQTT_PORT", "1883")))
    parser.add_argument("--enterprise", default=_env("ENTERPRISE", DEFAULT_ENTERPRISE))
    parser.add_argument("--site", default=_env("SITE", DEFAULT_SITE))
    parser.add_argument("--site-id", default=_env("SITE_ID", DEFAULT_SITE_ID))
    parser.add_argument("--boot-id", default=_env("BOOT_ID", ""))
    parser.add_argument("--topic-prefix", default=_env("TOPIC_PREFIX", DEFAULT_TOPIC_PREFIX))
    parser.add_argument(
        "--interval",
        type=float,
        default=float(_env("INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))),
    )
    parser.add_argument("--tls", action="store_true", default=_env_bool("MQTT_TLS"))
    parser.add_argument("--tls-verify", action="store_true", default=_env_bool("MQTT_TLS_VERIFY", True))
    parser.add_argument("--ca-file", default=_env("MQTT_CA_FILE", ""))
    parser.add_argument("--cert-file", default=_env("MQTT_CERT_FILE", ""))
    parser.add_argument("--key-file", default=_env("MQTT_KEY_FILE", ""))
    parser.add_argument("--username", default=_env("MQTT_USERNAME", ""))
    parser.add_argument("--password", default=_env("MQTT_PASSWORD", ""))
    parser.add_argument("--credentials-file", default=_env("MQTT_CREDENTIALS_FILE", ""))
    parser.add_argument("--tls-config-file", default=_env("MQTT_TLS_CONFIG_FILE", ""))
    parser.add_argument("--acceptance-mode", action="store_true", default=_env_bool("ACCEPTANCE_MODE"))
    parser.add_argument("--malformed-mode", action="store_true", default=_env_bool("MALFORMED_MODE"))
    parser.add_argument("--run-id", default=_env("RUN_ID", ""))
    parser.add_argument("--seed", type=int, default=int(_env("SEED", "0") or "0"))
    parser.add_argument("--case-count", type=int, default=int(_env("CASE_COUNT", "0") or "0"))
    parser.add_argument("--client-id-prefix", default=_env("CLIENT_ID_PREFIX", "uns_multi_system_sim"))
    parser.add_argument("--once", action="store_true", help="Publish one cycle and exit")
    args = parser.parse_args(argv)

    credentials = _load_secret_file(args.credentials_file)
    tls_config = _load_secret_file(args.tls_config_file)
    username = args.username or credentials.get("MQTT_USERNAME")
    password = args.password or credentials.get("MQTT_PASSWORD")
    ca_file = args.ca_file or tls_config.get("MQTT_CA_FILE")
    cert_file = args.cert_file or tls_config.get("MQTT_CERT_FILE")
    key_file = args.key_file or tls_config.get("MQTT_KEY_FILE")

    publisher = MultiSystemPublisher(
        host=args.host,
        port=args.port,
        enterprise=args.enterprise,
        site=args.site,
        site_id=args.site_id,
        boot_id=args.boot_id or None,
        interval_seconds=args.interval,
        topic_prefix=args.topic_prefix,
        tls=args.tls,
        ca_file=ca_file or None,
        cert_file=cert_file or None,
        key_file=key_file or None,
        tls_verify=args.tls_verify,
        username=username or None,
        password=password or None,
        acceptance_mode=args.acceptance_mode,
        run_id=args.run_id or None,
        seed=args.seed or None,
        case_count=args.case_count,
        malformed_mode=args.malformed_mode,
        identity_file=IDENTITY_FILE,
        client_id_prefix=args.client_id_prefix,
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
