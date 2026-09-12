"""One-shot enrollment and credential installation."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from uns_edge_agent.cloud_client import CloudClient, CloudClientError
from uns_edge_agent.config import AgentConfig
from uns_edge_agent.credentials import CredentialStore, generate_key_pair

LOGGER = logging.getLogger(__name__)
_SENSITIVE_MARKERS = ("enrollment_token", "token")


def enroll(
    *,
    config: AgentConfig,
    enrollment_token: str,
    cloud_client: CloudClient | None = None,
) -> str:
    """Generate keys locally, enroll, and atomically install credentials."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.enrollment_dir.mkdir(parents=True, exist_ok=True)
    enrollment_dir = config.enrollment_dir
    management_key = generate_key_pair("management")
    mqtt_key = generate_key_pair("mqtt")
    (enrollment_dir / "management.csr.pem").write_text(management_key.csr_pem, encoding="utf-8")
    (enrollment_dir / "mqtt.csr.pem").write_text(mqtt_key.csr_pem, encoding="utf-8")

    client = cloud_client or CloudClient(
        config.cloud_base_url,
        CredentialStore(config.credentials_dir),
        request_timeout_seconds=config.request_timeout_seconds,
        connect_timeout_seconds=config.connect_timeout_seconds,
    )
    try:
        response = client.enroll(
            enrollment_token=enrollment_token,
            management_csr=management_key.csr_pem,
            mqtt_csr=mqtt_key.csr_pem,
        )
    except CloudClientError:
        _erase_enrollment_dir(enrollment_dir)
        raise

    material = CredentialStore.enrollment_material_from_response(response)
    store = CredentialStore(config.credentials_dir)
    store.install_enrollment(material, management_key, mqtt_key)
    _erase_enrollment_dir(enrollment_dir)
    LOGGER.info("edge enrolled edge_id=%s", material.edge_id)
    return material.edge_id


def _erase_enrollment_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _safe_log_record(record: logging.LogRecord) -> bool:
    message = record.getMessage()
    return not any(marker in message for marker in _SENSITIVE_MARKERS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().addFilter(_safe_log_record)
    parser = argparse.ArgumentParser(description="Enroll this edge with the cloud management API")
    parser.add_argument("--token", required=True, help="Single-use enrollment token")
    parser.add_argument("--cloud-url", dest="cloud_url")
    parser.add_argument("--data-dir", dest="data_dir")
    args = parser.parse_args()

    config = AgentConfig.from_env()
    if args.cloud_url:
        config = AgentConfig(
            cloud_base_url=args.cloud_url.rstrip("/"),
            data_dir=Path(args.data_dir) if args.data_dir else config.data_dir,
            edge_api_url=config.edge_api_url,
        )
    elif args.data_dir:
        config = AgentConfig(
            cloud_base_url=config.cloud_base_url,
            data_dir=Path(args.data_dir),
            edge_api_url=config.edge_api_url,
        )

    try:
        edge_id = enroll(config=config, enrollment_token=args.token)
    except CloudClientError as exc:
        print(f"enrollment failed: {exc.reason}", file=sys.stderr)
        sys.exit(1)
    print(edge_id)


if __name__ == "__main__":
    main()
