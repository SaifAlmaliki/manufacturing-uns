"""Private DMZ management API stub for qualification harness negative checks."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/api/v1/health"}:
            self.send_response(404)
            self.end_headers()
            return
        payload = {
            "status": "healthy",
            "service": "dmz-management-stub",
            "api_version": "v1",
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8443), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
