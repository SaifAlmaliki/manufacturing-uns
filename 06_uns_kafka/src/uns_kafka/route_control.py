"""Private authenticated mapper route-control endpoint.

Activation requests are enqueued for the ingestion owner thread instead of
mutating active routes from the HTTP handler thread.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from uns_config.route_release import (
    RouteRelease,
    is_stale_activation_report,
    mapper_topic_filters,
    route_release_from_dict,
)
from uns_config.publication_routes import PublicationRoute

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ActiveMapperRelease:
    revision: int
    digest: str
    publication_routes: tuple[PublicationRoute, ...]
    topic_filters: tuple[str, ...]


class RouteControlState:
    """Thread-safe queue and active mapper release state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: deque[RouteRelease] = deque()
        self._active: ActiveMapperRelease | None = None

    def enqueue(self, release: RouteRelease) -> None:
        with self._lock:
            self._pending.append(release)

    def drain_pending(self) -> RouteRelease | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pending.popleft()

    def apply_release(self, release: RouteRelease) -> ActiveMapperRelease:
        active = ActiveMapperRelease(
            revision=release.revision,
            digest=release.digest,
            publication_routes=release.publication_routes,
            topic_filters=mapper_topic_filters(release),
        )
        with self._lock:
            self._active = active
        return active

    def active(self) -> ActiveMapperRelease | None:
        with self._lock:
            return self._active

    def report_activation(self, revision: int, digest: str) -> ActiveMapperRelease:
        with self._lock:
            current = self._active
            if current is not None and is_stale_activation_report(
                reported_revision=revision,
                active_revision=current.revision,
            ):
                raise RouteControlError("stale_activation_report", revision)
            if current is None or current.revision != revision or current.digest != digest:
                raise RouteControlError("activation_mismatch", revision)
            return current


class RouteControlError(Exception):
    def __init__(self, reason: str, detail: str | int = "") -> None:
        self.reason = reason
        self.detail = detail
        message = reason if detail == "" else f"{reason}: {detail}"
        super().__init__(message)


class RouteControlServer:
    def __init__(
        self,
        state: RouteControlState,
        *,
        host: str,
        port: int,
        token: str,
    ) -> None:
        self._state = state
        self._token = token
        self._httpd = ThreadingHTTPServer((host, port), self._handler_factory())
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address
        return host, port

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _handler_factory(self):
        state = self._state
        token = self._token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A003
                LOGGER.debug(format, *args)

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                return header == f"Bearer {token}"

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                return json.loads(self.rfile.read(length))

            def _write_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if self.path != "/internal/route-control/v1/active":
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                active = state.active()
                if active is None:
                    self._write_json(HTTPStatus.OK, {"revision": 0, "digest": "", "topic_filters": []})
                    return
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "revision": active.revision,
                        "digest": active.digest,
                        "topic_filters": list(active.topic_filters),
                    },
                )

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                try:
                    payload = self._read_json()
                    if self.path == "/internal/route-control/v1/releases":
                        release = route_release_from_dict(payload)
                        state.enqueue(release)
                        self._write_json(HTTPStatus.ACCEPTED, {"queued_revision": release.revision})
                        return
                    if self.path == "/internal/route-control/v1/activation-report":
                        revision = int(payload["revision"])
                        digest = str(payload["digest"])
                        active = state.report_activation(revision, digest)
                        self._write_json(
                            HTTPStatus.OK,
                            {"revision": active.revision, "digest": active.digest},
                        )
                        return
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                except RouteControlError as exc:
                    status = HTTPStatus.CONFLICT if exc.reason == "stale_activation_report" else HTTPStatus.BAD_REQUEST
                    self._write_json(status, {"error": exc.reason, "detail": str(exc.detail)})
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("route control request failed")
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(exc)})

        return Handler
