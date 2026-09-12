#!/usr/bin/env python3
"""Validate a production cloud bundle before installation."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}$")
SUPPORTED_CONTRACT_VERSION = 1
SUPPORTED_ENVELOPE_VERSION = 2


class ValidationError(Exception):
    pass


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_release(bundle_dir: Path) -> dict:
    release_path = bundle_dir / "release.json"
    if not release_path.is_file():
        raise ValidationError(f"missing release manifest: {release_path}")
    return json.loads(release_path.read_text(encoding="utf-8"))


def _load_settings(bundle_dir: Path) -> dict:
    settings_path = bundle_dir / "settings.yaml"
    if not settings_path.is_file():
        example = bundle_dir / "settings.yaml.example"
        if example.is_file():
            raise ValidationError(
                "settings.yaml is missing; copy settings.yaml.example and customize it"
            )
        raise ValidationError(f"missing settings file: {settings_path}")
    document = _load_yaml(settings_path)
    return document.get("default", document)


def _require_tls_material(bundle_dir: Path) -> None:
    required = [
        "secrets/tls/console/fullchain.pem",
        "secrets/tls/console/privkey.pem",
        "secrets/tls/enrollment/fullchain.pem",
        "secrets/tls/enrollment/privkey.pem",
        "secrets/tls/management/fullchain.pem",
        "secrets/tls/management/privkey.pem",
        "secrets/tls/management/ca.pem",
        "secrets/broker-tls/broker-keystore.jks",
        "secrets/broker-tls/broker-truststore.jks",
    ]
    missing = [relative for relative in required if not (bundle_dir / relative).is_file()]
    if missing:
        raise ValidationError("missing TLS or broker key material: " + ", ".join(missing))


def _validate_release_contract(release: dict) -> None:
    if release.get("bundle_version") != 1:
        raise ValidationError(f"unsupported bundle_version: {release.get('bundle_version')}")
    if release.get("contract_version") != SUPPORTED_CONTRACT_VERSION:
        raise ValidationError(
            f"unsupported contract_version: {release.get('contract_version')}; "
            f"expected {SUPPORTED_CONTRACT_VERSION}"
        )
    if release.get("envelope_version") != SUPPORTED_ENVELOPE_VERSION:
        raise ValidationError(
            f"unsupported envelope_version: {release.get('envelope_version')}; "
            f"expected {SUPPORTED_ENVELOPE_VERSION}"
        )
    broker = release.get("images", {}).get("hivemq-broker", {})
    if broker.get("status") != "qualified":
        blocker = broker.get("blocker", "broker image is not qualified")
        raise ValidationError(f"unqualified central broker release: {blocker}")
    for name, image in release.get("images", {}).items():
        digest = image.get("digest")
        if not digest or not DIGEST_PATTERN.fullmatch(digest):
            raise ValidationError(f"image {name} is missing a digest-pinned reference")


def _validate_public_origin(settings: dict) -> None:
    platform = settings.get("platform", {}) or {}
    origin = str(platform.get("public_origin", "")).strip()
    if not origin:
        raise ValidationError("platform.public_origin is required")
    if not origin.startswith("https://"):
        raise ValidationError("platform.public_origin must use HTTPS in production")
    if "localhost" in origin or "127.0.0.1" in origin:
        raise ValidationError("platform.public_origin must not reference localhost")


def _validate_capacity(release: dict, bundle_dir: Path) -> None:
    capacity = release.get("capacity", {})
    minimum_data = int(capacity.get("minimum_data_disk_gb", 0))
    minimum_root = int(capacity.get("minimum_root_disk_gb", 0))
    if minimum_data <= 0 or minimum_root <= 0:
        raise ValidationError("release capacity budget is incomplete")

    settings = _load_settings(bundle_dir)
    operations = settings.get("operations", {}) or {}
    backup = operations.get("backup", {}) or {}
    retention_days = int(backup.get("retention_days", 0))
    kafka_retention_ms = int(capacity.get("kafka_retention_ms", 0))
    if retention_days <= 0 or kafka_retention_ms <= 0:
        raise ValidationError("backup retention or Kafka retention budget is not declared")

    total, used, free = shutil.disk_usage(bundle_dir)
    free_gb = free / (1024**3)
    required_gb = minimum_root + minimum_data
    if free_gb < required_gb:
        raise ValidationError(
            f"insufficient declared disk budget: need at least {required_gb} GiB free, found {free_gb:.1f} GiB"
        )


def _validate_compose(bundle_dir: Path) -> None:
    compose_path = bundle_dir / "compose.yml"
    if not compose_path.is_file():
        raise ValidationError(f"missing compose file: {compose_path}")
    compose = _load_yaml(compose_path)
    services = compose.get("services", {})
    forbidden = (
        "hivemq-edge",
        "oee_mqtt_simulator",
        "multi_system_simulator",
        "opcua_client",
        "opcua-simulator",
        "modbus-simulator",
    )
    for name in forbidden:
        if name in services:
            raise ValidationError(f"forbidden service present in cloud compose: {name}")
    compose_text = compose_path.read_text(encoding="utf-8")
    if "start-dev" in compose_text:
        raise ValidationError("compose must not use Keycloak start-dev")
    if ":latest" in compose_text:
        raise ValidationError("compose must not reference floating :latest image tags")


def validate_bundle(bundle_dir: Path, *, check_disk: bool = True) -> None:
    release = _load_release(bundle_dir)
    settings = _load_settings(bundle_dir)
    _require_tls_material(bundle_dir)
    _validate_public_origin(settings)
    _validate_compose(bundle_dir)
    _validate_release_contract(release)
    if check_disk:
        _validate_capacity(release, bundle_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Path to deploy/cloud bundle directory",
    )
    parser.add_argument(
        "--skip-disk-check",
        action="store_true",
        help="Skip host free-space verification (useful in CI fixture directories)",
    )
    args = parser.parse_args(argv)
    try:
        validate_bundle(args.bundle_dir.resolve(), check_disk=not args.skip_disk_check)
    except ValidationError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print("validation ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
