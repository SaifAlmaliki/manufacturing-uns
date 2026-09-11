"""CLI helpers invoked from qualification containers for HTTP and lake queries."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CA_DIR = Path("/qualification-ca")
CLOUD_MANAGEMENT_HOST = "cloud-management"
CLOUD_MANAGEMENT_PORT = 443
HISTORIC_TOPIC = "uns.historic-events"
LAKE_BUCKET = "uns-historic-events"


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(CA_DIR / "ca.crt"))
    return context


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
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
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def cmd_enroll(args: argparse.Namespace) -> int:
    identity = _request("POST", "/api/v1/edges/enroll", {"edge_id": args.edge_id})
    print(json.dumps(identity, separators=(",", ":")))
    return 0


def cmd_save_connection(args: argparse.Namespace) -> int:
    settings = json.loads(args.settings)
    result = _request(
        "POST",
        f"/api/v1/edges/{args.edge_id}/connections",
        {"protocol": args.protocol, "settings": settings},
    )
    print(json.dumps(result, separators=(",", ":")))
    return 0


def cmd_wait_applied(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            report = _request(
                "GET",
                f"/api/v1/edges/{args.edge_id}/connections/{args.revision}",
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            report = None
        if report and report.get("phase") == "applied":
            print(json.dumps(report, separators=(",", ":")))
            return 0
        time.sleep(1.0)
    print(
        json.dumps(
            {
                "error": "timeout",
                "edge_id": args.edge_id,
                "revision": args.revision,
            }
        ),
        file=sys.stderr,
    )
    return 1


def _minio_client():
    from minio import Minio

    return Minio(
        "cloud-minio:9000",
        access_key="qualification",
        secret_key="qualification-test-only",
        secure=False,
    )


def _lake_rows(event_id: str) -> list[dict[str, Any]]:
    client = _minio_client()
    rows: list[dict[str, Any]] = []
    prefix = f"events/{event_id}/"
    for obj in client.list_objects(LAKE_BUCKET, prefix=prefix, recursive=True):
        response = client.get_object(LAKE_BUCKET, obj.object_name)
        rows.append(json.loads(response.read().decode("utf-8")))
        response.close()
        response.release_conn()
    rows.sort(key=lambda row: (row.get("kafka_partition", 0), row.get("kafka_offset", 0)))
    return rows


def cmd_lake_rows(args: argparse.Namespace) -> int:
    print(json.dumps(_lake_rows(args.event_id), separators=(",", ":")))
    return 0


def cmd_kafka_rows(args: argparse.Namespace) -> int:
    from confluent_kafka import Consumer, KafkaException

    config = {
        "bootstrap.servers": "cloud-kafka:29092",
        "group.id": f"qualification-harness-{args.event_id}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    consumer = Consumer(config)
    consumer.subscribe([HISTORIC_TOPIC])
    deadline = time.monotonic() + args.timeout
    rows: list[dict[str, Any]] = []
    try:
        while time.monotonic() < deadline:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            payload = json.loads(message.value().decode("utf-8"))
            if payload.get("event_id") == args.event_id:
                rows.append(
                    {
                        "event_id": payload.get("event_id"),
                        "kafka_partition": message.partition(),
                        "kafka_offset": message.offset(),
                        "topic": message.topic(),
                    }
                )
            if rows and time.monotonic() > deadline - 1.0:
                break
    finally:
        consumer.close()
    print(json.dumps(rows, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll = subparsers.add_parser("enroll")
    enroll.add_argument("--edge-id", required=True)
    enroll.set_defaults(func=cmd_enroll)

    save = subparsers.add_parser("save-connection")
    save.add_argument("--edge-id", required=True)
    save.add_argument("--protocol", required=True)
    save.add_argument("--settings", required=True)
    save.set_defaults(func=cmd_save_connection)

    wait = subparsers.add_parser("wait-applied")
    wait.add_argument("--edge-id", required=True)
    wait.add_argument("--revision", type=int, required=True)
    wait.add_argument("--timeout", type=float, default=30.0)
    wait.set_defaults(func=cmd_wait_applied)

    lake = subparsers.add_parser("lake-rows")
    lake.add_argument("--event-id", required=True)
    lake.set_defaults(func=cmd_lake_rows)

    kafka = subparsers.add_parser("kafka-rows")
    kafka.add_argument("--event-id", required=True)
    kafka.add_argument("--timeout", type=float, default=5.0)
    kafka.set_defaults(func=cmd_kafka_rows)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
