"""Health probe distinguishing process, cloud, journal, and Edge API reachability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from uns_edge_agent.cloud_client import CloudClient, CloudClientError
from uns_edge_agent.config import AgentConfig
from uns_edge_agent.credentials import CredentialStore
from uns_edge_agent.journal import Journal, JournalLockError


def probe_edge_api(url: str | None, timeout_seconds: float = 5.0) -> bool:
    if not url:
        return False
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def health_payload(config: AgentConfig) -> dict[str, Any]:
    credentials = CredentialStore(config.credentials_dir)
    journal = Journal(config.journal_path)
    payload: dict[str, Any] = {
        "status": "ok",
        "process": True,
        "journal_available": False,
        "cloud_connected": False,
        "edge_api_reachable": probe_edge_api(config.edge_api_url),
        "credentials_installed": credentials.has_credentials(),
    }
    try:
        journal.open()
        payload["journal_available"] = True
        journal.close()
    except JournalLockError:
        payload["status"] = "degraded"
        payload["reason"] = "journal_locked"
        return payload

    if credentials.has_credentials():
        client = CloudClient(
            config.cloud_base_url,
            credentials,
            request_timeout_seconds=config.request_timeout_seconds,
            connect_timeout_seconds=config.connect_timeout_seconds,
        )
        try:
            client.open_session("healthcheck")
            payload["cloud_connected"] = True
        except CloudClientError:
            payload["status"] = "degraded"
            payload["reason"] = "cloud_unreachable"

    if not payload["journal_available"]:
        payload["status"] = "degraded"
        payload["reason"] = "journal_unavailable"
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Check edge agent health")
    parser.add_argument("--data-dir", dest="data_dir")
    parser.add_argument("--cloud-url", dest="cloud_url")
    parser.add_argument("--edge-api-url", dest="edge_api_url")
    args = parser.parse_args()

    config = AgentConfig.from_env()
    if args.data_dir or args.cloud_url or args.edge_api_url:
        config = AgentConfig(
            cloud_base_url=(args.cloud_url or config.cloud_base_url).rstrip("/"),
            data_dir=Path(args.data_dir) if args.data_dir else config.data_dir,
            edge_api_url=args.edge_api_url or config.edge_api_url,
        )

    payload = health_payload(config)
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    if payload.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
