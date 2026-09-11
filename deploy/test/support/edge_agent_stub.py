"""Edge agent stub that probes private DMZ management and reports health."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MANAGEMENT_URL = os.environ.get(
    "EDGE_MANAGEMENT_URL",
    "http://dmz-management:8443/health",
)


def probe_management() -> dict:
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


def main() -> None:
    while True:
        result = probe_management()
        print(json.dumps({"agent_probe": result}), flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
