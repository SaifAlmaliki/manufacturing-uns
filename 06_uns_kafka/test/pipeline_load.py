"""Publish deterministic pipeline load to MQTT for qualification runs.

Credentials come from mounted Dynaconf settings only; never pass secrets on the CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from uns_config import get_settings

from uns_kafka.pipeline_fixture import LoadReport, PipelineCounters, generate_fixture, validate_report_parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish deterministic UNS pipeline load over MQTT.")
    parser.add_argument("--sites", type=int, required=True, help="Number of simulated sites.")
    parser.add_argument("--topics", type=int, required=True, help="Topics per site.")
    parser.add_argument("--rate", type=float, required=True, help="Sustained publish rate in events/s.")
    parser.add_argument("--seconds", type=float, required=True, help="Total run duration in seconds.")
    parser.add_argument("--burst-rate", type=float, default=None, help="Optional burst publish rate in events/s.")
    parser.add_argument(
        "--burst-seconds",
        type=float,
        default=None,
        help="Optional burst duration starting at t=0.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to write the JSON report. Parent directory must already exist.",
    )
    return parser.parse_args(argv)


def _validate_report_path(report_path: Path) -> None:
    try:
        validate_report_parent(report_path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


def _connect_client(settings) -> mqtt.Client:
    host = settings.get("mqtt.host")
    if not host:
        raise SystemExit("mqtt.host is not configured in conf/settings.yaml")
    port = int(settings.get("mqtt.port", 1883))
    client_id = settings.get("mqtt.client_id") or "uns_pipeline_load"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    username = settings.get("mqtt.username")
    password = settings.get("mqtt.password")
    if username:
        client.username_pw_set(username, password)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    return client


def _current_rate(*, elapsed: float, args: argparse.Namespace) -> float:
    if args.burst_rate is None or args.burst_seconds is None:
        return args.rate
    if elapsed < args.burst_seconds:
        return args.burst_rate
    return args.rate


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _validate_report_path(args.report)

    settings = get_settings("kafka_mapper")
    manifest = generate_fixture(sites=args.sites, topics=args.topics)
    client = _connect_client(settings)

    started_at = datetime.now(tz=UTC)
    counters = PipelineCounters()
    interval_start = time.monotonic()
    run_start = interval_start
    index = 0
    total = len(manifest.publications)

    try:
        while True:
            elapsed = time.monotonic() - run_start
            if elapsed >= args.seconds:
                break
            rate = _current_rate(elapsed=elapsed, args=args)
            if rate <= 0:
                raise SystemExit("--rate and --burst-rate must be positive")

            target_sent = min(total, int(elapsed * rate))
            while index < target_sent:
                publication = manifest.publications[index]
                payload = json.dumps(publication.payload, separators=(",", ":"))
                result = client.publish(publication.topic, payload, qos=1)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"MQTT publish failed with rc={result.rc}")
                counters.source_receipts += 1
                index += 1
            time.sleep(0.01)
    finally:
        client.loop_stop()
        client.disconnect()

    finished_at = datetime.now(tz=UTC)
    report = LoadReport(
        sites=args.sites,
        topics=args.topics,
        rate=args.rate,
        seconds=args.seconds,
        burst_rate=args.burst_rate,
        burst_seconds=args.burst_seconds,
        manifest_digest=manifest.manifest_digest,
        source_receipts=counters.source_receipts,
        counters=counters,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
    )
    args.report.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
