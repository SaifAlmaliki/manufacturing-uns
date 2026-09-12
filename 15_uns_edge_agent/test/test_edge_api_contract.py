"""Live HiveMQ Edge API contract tests (skipped without a licensed instance)."""

from __future__ import annotations

import json
import os

import httpx
import pytest

from uns_config.edge_config_digest import configuration_digest
from uns_config.edge_contracts import decode_edge_config
from uns_edge_agent.edge_client import HiveMQEdgeClient
from uns_edge_agent.reconcile import Reconciler

from test_protocols import ALLOWLIST, _modbus_adapter, _opc_ua_adapter

SKIP_REASON = (
    "No licensed/pinned HiveMQ Edge instance available. "
    "Set UNS_EDGE_API_CONTRACT_URL, UNS_EDGE_API_USERNAME, and UNS_EDGE_API_PASSWORD "
    "to run live adapter persistence checks."
)


def _edge_settings() -> tuple[str, str, str] | None:
    base_url = os.environ.get("UNS_EDGE_API_CONTRACT_URL")
    username = os.environ.get("UNS_EDGE_API_USERNAME")
    password = os.environ.get("UNS_EDGE_API_PASSWORD")
    if not base_url or not username or not password:
        return None
    return base_url, username, password


def _edge_reachable(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/v1/auth/authenticate", timeout=2.0)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


@pytest.fixture
def live_edge_client():
    settings = _edge_settings()
    if settings is None:
        pytest.skip(SKIP_REASON)
    base_url, username, password = settings
    if not _edge_reachable(base_url):
        pytest.skip(SKIP_REASON)
    client = HiveMQEdgeClient(base_url, username=username, password=password)
    yield client
    client.close()


def _config_document():
    document = {
        "contract_version": 1,
        "edge_id": "edge-contract-test",
        "revision": 99_001,
        "adapters": [
            {
                "adapter_id": adapter.adapter_id,
                "protocol": adapter.protocol,
                "connection": dict(adapter.connection),
                "tags": [dict(tag) for tag in adapter.tags],
                "northbound_mappings": [dict(mapping) for mapping in adapter.northbound_mappings],
            }
            for adapter in (_opc_ua_adapter(), _modbus_adapter())
        ],
        "required_route_revision": 1,
        "secret_refs": [],
        "deleted_adapter_ids": [],
    }
    document["digest"] = configuration_digest(document)
    return document


def test_live_edge_applies_and_readback_matches(live_edge_client: HiveMQEdgeClient):
    config = decode_edge_config(json.dumps(_config_document()).encode("utf-8"))
    reconciler = Reconciler(
        live_edge_client,
        boot_id="contract-boot",
        endpoint_allowlist=ALLOWLIST,
    )
    report = reconciler.apply(config)
    assert report.phase == "applied"
    owned = live_edge_client.read_owned(config.edge_id)
    assert "catalog-opcua-sim" in owned
    assert "catalog-modbus-sim" in owned
