"""Edge agent stub that polls cloud management and reports applied revisions."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MANAGEMENT_URL = os.environ.get(
    "EDGE_MANAGEMENT_URL",
    "http://dmz-management:8443/health",
)
CLOUD_MANAGEMENT_HOST = os.environ.get("CLOUD_MANAGEMENT_HOST", "cloud-management")
CLOUD_MANAGEMENT_PORT = int(os.environ.get("CLOUD_MANAGEMENT_PORT", "443"))
EDGE_ID = os.environ.get("EDGE_ID", "edge-01")
CA_DIR = Path("/qualification-ca")
APPLY_DELAY_SECONDS = float(os.environ.get("EDGE_APPLY_DELAY_SECONDS", "2"))


def probe_management() -> dict[str, Any]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(MANAGEMENT_URL, timeout=3) as response:
            body = response.read().decode("utf-8")
            return {
                "healthy": response.status == 200,
                "status_code": response.status,
                "body": json.loads(body),
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
    except urllib.error.URLError as exc:
        return {
            "healthy": False,
            "error": str(exc),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def _cloud_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    context = ssl.create_default_context(cafile=str(CA_DIR / "ca.crt"))
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
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _pending_connections() -> list[tuple[int, dict[str, Any]]]:
    try:
        edge = _cloud_request("GET", f"/api/v1/edges/{EDGE_ID}")
    except urllib.error.HTTPError:
        return []
    revisions: list[tuple[int, dict[str, Any]]] = []
    for revision, connection in edge.get("connections", {}).items():
        if connection.get("phase") in {"pending", "applying"}:
            revisions.append((int(revision), connection))
    return sorted(revisions)


def _poll_and_apply() -> None:
    for revision, connection in _pending_connections():
        if connection.get("phase") != "pending":
            continue
        time.sleep(APPLY_DELAY_SECONDS)
        _cloud_request(
            "POST",
            f"/api/v1/edges/{EDGE_ID}/connections/{revision}/report",
            {"phase": "applied"},
        )
        print(
            json.dumps(
                {
                    "edge_apply": {
                        "edge_id": EDGE_ID,
                        "revision": revision,
                        "protocol": connection.get("protocol"),
                        "phase": "applied",
                    }
                }
            ),
            flush=True,
        )


def main() -> None:
    while True:
        result = probe_management()
        print(json.dumps({"agent_probe": result}), flush=True)
        _poll_and_apply()
        time.sleep(2)


if __name__ == "__main__":
    main()
