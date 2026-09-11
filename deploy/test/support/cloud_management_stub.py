"""Cloud management API stub for enrollment and desired-state polling."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE: dict[str, dict] = {
    "edges": {},
    "connections": {},
}


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

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "healthy", "service": "cloud-management-stub"})
            return
        if self.path.startswith("/api/v1/edges/"):
            edge_id = self.path.split("/")[-1]
            edge = STATE["edges"].get(edge_id)
            if edge is None:
                self._json(404, {"error": "edge_not_found"})
                return
            self._json(200, edge)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        if self.path.endswith("/enroll"):
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
        if "/connections" in self.path:
            edge_id = self.path.split("/")[4]
            revision = len(STATE["connections"].get(edge_id, {})) + 1
            STATE.setdefault("connections", {}).setdefault(edge_id, {})[revision] = {
                "revision": revision,
                "protocol": payload.get("protocol"),
                "settings": payload.get("settings", {}),
                "phase": "pending",
            }
            self._json(201, {"revision": revision, "phase": "pending"})
            return
        self._json(404, {"error": "not_found"})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 443), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
