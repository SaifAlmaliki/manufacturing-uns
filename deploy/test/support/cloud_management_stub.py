"""Cloud management API stub for enrollment and desired-state polling."""

from __future__ import annotations

import argparse
import json
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

STATE: dict[str, Any] = {
    "edges": {},
    "connections": {},
}
CA_DIR = Path("/qualification-ca")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(
                200,
                {
                    "status": "healthy",
                    "service": "cloud-management-stub",
                    "tls": True,
                    "ca_subject": "CN=qualification-ca.uns",
                },
            )
            return
        if self.path.startswith("/api/v1/edges/") and "/connections/" in self.path:
            parts = self.path.strip("/").split("/")
            edge_id = parts[3]
            revision = int(parts[5])
            connection = STATE["connections"].get(edge_id, {}).get(revision)
            if connection is None:
                self._json(404, {"error": "connection_not_found"})
                return
            edge = STATE["edges"].get(edge_id, {})
            self._json(
                200,
                {
                    "edge_id": edge_id,
                    "revision": revision,
                    "desired_revision": revision,
                    "applied_revision": connection.get("applied_revision", 0),
                    "phase": connection["phase"],
                    "protocol": connection.get("protocol"),
                    "certificate_subject": edge.get("management_subject"),
                },
            )
            return
        if self.path.startswith("/api/v1/edges/") and self.path.count("/") == 4:
            edge_id = self.path.rstrip("/").split("/")[-1]
            edge = STATE["edges"].get(edge_id)
            if edge is None:
                self._json(404, {"error": "edge_not_found"})
                return
            payload = dict(edge)
            payload["connections"] = STATE["connections"].get(edge_id, {})
            self._json(200, payload)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        if self.path == "/api/v1/edges/enroll":
            edge_id = payload["edge_id"]
            identity = {
                "edge_id": edge_id,
                "management_subject": f"CN={edge_id}.management.qualification.uns",
                "bridge_subject": f"CN={edge_id}.bridge.qualification.uns",
                "enrolled": True,
            }
            STATE["edges"][edge_id] = identity
            self._json(201, identity)
            return
        if "/connections/" in self.path and self.path.endswith("/report"):
            parts = self.path.strip("/").split("/")
            edge_id = parts[3]
            revision = int(parts[5])
            connection = STATE["connections"].get(edge_id, {}).get(revision)
            if connection is None:
                self._json(404, {"error": "connection_not_found"})
                return
            connection["phase"] = payload.get("phase", "applied")
            connection["applied_revision"] = revision
            connection["applied_at"] = time.time()
            self._json(200, connection)
            return
        if self.path.endswith("/connections"):
            edge_id = self.path.strip("/").split("/")[3]
            revision = len(STATE["connections"].get(edge_id, {})) + 1
            STATE.setdefault("connections", {}).setdefault(edge_id, {})[revision] = {
                "revision": revision,
                "protocol": payload.get("protocol"),
                "settings": payload.get("settings", {}),
                "phase": "pending",
                "created_at": time.time(),
            }
            self._json(201, {"revision": revision, "phase": "pending"})
            return
        self._json(404, {"error": "not_found"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--tls-cert", default=str(CA_DIR / "server.crt"))
    parser.add_argument("--tls-key", default=str(CA_DIR / "server.key"))
    args = parser.parse_args()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.tls_cert, args.tls_key)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
