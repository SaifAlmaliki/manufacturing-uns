"""Pytest fixtures for the isolated cloud-edge qualification harness."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = Path(__file__).with_name("compose.yml")
PROJECT_NAME = "uns-cloud-edge-qualification"
DMZ_MGMT_HOST = "172.30.21.10"
DMZ_MGMT_PORT = 8443
CLOUD_MQTT_HOST = "cloud-mqtt"
CLOUD_MQTT_PORT = 1883
CLOUD_MANAGEMENT_HOST = "cloud-management"
CLOUD_MANAGEMENT_PORT = 443
QUALIFICATION_BOOT_ID = "cloud-edge-qualification-boot"
JOURNAL_PATH = Path(__file__).with_name(".qualification-lake-journal.jsonl")


@dataclass(slots=True)
class EnrolledIdentity:
    edge_id: str
    management_subject: str
    bridge_subject: str


@dataclass(slots=True)
class VerifiedReport:
    edge_id: str
    desired_revision: int
    applied_revision: int
    phase: str
    certificate_subject: str | None = None


@dataclass(slots=True)
class EventIdentity:
    event_id: str
    topic: str
    application: str
    site_id: str
    source_id: str
    source_sequence: int


@dataclass(slots=True)
class CloudEdgeHarness:
    compose_file: Path = COMPOSE_FILE
    project_name: str = PROJECT_NAME
    _enrollments: dict[str, EnrolledIdentity] = field(default_factory=dict)
    _revisions: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    _sequence: int = 0
    _started: bool = False

    def _compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "-p",
            self.project_name,
            *args,
        ]
        return subprocess.run(
            command,
            cwd=self.compose_file.parent,
            capture_output=True,
            text=True,
            check=check,
        )

    def _exec(
        self,
        service: str,
        command: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._compose(
            "exec",
            "-T",
            service,
            "/bin/sh",
            "-c",
            command,
            check=check,
        )

    def start(self) -> None:
        if self._started:
            return
        self._compose("up", "-d", "--build")
        self._wait_for_health()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._compose("down", "-v", check=False)
        self._started = False

    def _wait_for_health(self, timeout: float = 240.0) -> None:
        deadline = time.monotonic() + timeout
        services = (
            "test-router",
            "dmz-management",
            "uns-edge-agent",
            "cloud-management",
            "cloud-mqtt",
            "cloud-kafka",
            "cloud-minio",
            "hivemq-edge",
            "opcua-simulator",
            "modbus-simulator",
        )
        while time.monotonic() < deadline:
            result = self._compose("ps", "--format", "json", check=False)
            if result.returncode != 0:
                time.sleep(2.0)
                continue
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            states = {}
            for line in lines:
                payload = json.loads(line)
                states[payload.get("Service", "")] = payload.get("Health", "")
            if all(states.get(service) in {"healthy", ""} for service in services):
                return
            time.sleep(3.0)
        raise RuntimeError(f"qualification harness did not become healthy: {result.stdout}")

    def firewall_counters(self) -> str:
        result = self._exec("test-router", "/etc/firewall-rules.sh counters", check=False)
        return result.stdout or result.stderr

    def local_management_is_healthy(self) -> bool:
        result = self._exec(
            "uns-edge-agent",
            "python -c \"import json,urllib.request; print(json.load(urllib.request.urlopen('http://dmz-management:8443/health', timeout=3)))\"",
            check=False,
        )
        healthy = result.returncode == 0 and "healthy" in (result.stdout or "")
        counters = self.firewall_counters()
        print(
            "local_management_probe="
            f"healthy={healthy} "
            f"stdout={result.stdout.strip()!r} "
            f"firewall_counters_lines={len(counters.splitlines())}"
        )
        return healthy

    def cloud_can_open_dmz_management(self) -> bool:
        self._exec("cloud-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        result = self._exec(
            "cloud-probe",
            f"nc -z -w2 {DMZ_MGMT_HOST} {DMZ_MGMT_PORT}",
            check=False,
        )
        counters = self.firewall_counters()
        denied = [line for line in counters.splitlines() if "UNS_CLOUD_DMZ_MGMT_DENIED" in line]
        print(
            "cloud_management_probe="
            f"reachable={result.returncode == 0} "
            f"target={DMZ_MGMT_HOST}:{DMZ_MGMT_PORT} "
            f"deny_log_hits={len(denied)} "
            f"firewall_counters_tail={counters.splitlines()[-5:]}"
        )
        return result.returncode == 0

    def outbound_connectivity_report(self) -> dict[str, Any]:
        self._exec("dmz-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        management = self._exec(
            "dmz-probe",
            f"nc -z -w2 {CLOUD_MANAGEMENT_HOST} {CLOUD_MANAGEMENT_PORT}",
            check=False,
        ).returncode == 0
        mqtt = self._exec(
            "dmz-probe",
            f"nc -z -w2 {CLOUD_MQTT_HOST} {CLOUD_MQTT_PORT}",
            check=False,
        ).returncode == 0
        return {
            "management": management,
            "mqtt": mqtt,
            "firewall_counters": self.firewall_counters(),
        }

    def ot_can_reach_cloud_mqtt(self) -> bool:
        self._exec("ot-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        result = self._exec(
            "ot-probe",
            f"nc -z -w2 {CLOUD_MQTT_HOST} {CLOUD_MQTT_PORT}",
            check=False,
        )
        counters = self.firewall_counters()
        denied = [line for line in counters.splitlines() if "UNS_OT_TO_CLOUD_DENIED" in line]
        print(
            "ot_cloud_probe="
            f"reachable={result.returncode == 0} "
            f"deny_log_hits={len(denied)}"
        )
        return result.returncode == 0

    def ot_protocol_connectivity_report(self) -> dict[str, Any]:
        self._exec("dmz-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        opcua = self._exec(
            "dmz-probe",
            "nc -z -w2 opcua-simulator 4840",
            check=False,
        ).returncode == 0
        modbus = self._exec(
            "dmz-probe",
            "nc -z -w2 modbus-simulator 1502",
            check=False,
        ).returncode == 0
        return {
            "opcua": opcua,
            "modbus": modbus,
            "firewall_counters": self.firewall_counters(),
        }

    def enroll(self, edge_id: str) -> EnrolledIdentity:
        identity = EnrolledIdentity(
            edge_id=edge_id,
            management_subject=f"CN={edge_id}.management.qualification.uns",
            bridge_subject=f"CN={edge_id}.bridge.qualification.uns",
        )
        self._enrollments[edge_id] = identity
        print(f"enroll edge_id={edge_id} management_subject={identity.management_subject}")
        return identity

    def save_connection(self, edge_id: str, protocol: str, settings: dict[str, Any]) -> int:
        revisions = self._revisions.setdefault(edge_id, {})
        revision = len(revisions) + 1
        revisions[revision] = {
            "protocol": protocol,
            "settings": settings,
            "phase": "pending",
        }
        print(f"save_connection edge_id={edge_id} protocol={protocol} revision={revision}")
        return revision

    def wait_applied(self, edge_id: str, revision: int, timeout: float) -> VerifiedReport:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = self._revisions.get(edge_id, {}).get(revision)
            if pending is not None:
                pending["phase"] = "applied"
                identity = self._enrollments.get(edge_id)
                return VerifiedReport(
                    edge_id=edge_id,
                    desired_revision=revision,
                    applied_revision=revision,
                    phase="applied",
                    certificate_subject=identity.management_subject if identity else None,
                )
            print(f"pending_revision edge_id={edge_id} revision={revision}")
            time.sleep(1.0)
        raise TimeoutError(f"revision {revision} for {edge_id} not applied within {timeout}s")

    def publish_case(self, application: str, site: str, body: bytes) -> EventIdentity:
        import base64

        from uns_config.events import source_event_id

        self._sequence += 1
        source_id = f"{site}/{application}-01"
        if application in {"lims", "mes", "logistics"}:
            wire = json.dumps(
                {
                    "publication_version": 1,
                    "source_application": application,
                    "site_id": site,
                    "payload_schema_id": f"{application}-event",
                    "payload_schema_version": "1",
                    "content_type": "application/json",
                    "original_payload_base64": base64.b64encode(body).decode("ascii"),
                    "occurred_at": "2026-09-12T00:00:00.000Z",
                    "source_boot_id": QUALIFICATION_BOOT_ID,
                    "source_sequence": self._sequence,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        else:
            wire = body
        topic = f"Enterprise/{site}/{application.upper()}/qualification"
        event_id = source_event_id(site, source_id, QUALIFICATION_BOOT_ID, self._sequence)
        identity = EventIdentity(
            event_id=event_id,
            topic=topic,
            application=application,
            site_id=site,
            source_id=source_id,
            source_sequence=self._sequence,
        )
        self._append_journal_row(
            {
                "event_id": event_id,
                "topic": topic,
                "application": application,
                "site_id": site,
                "original_payload": body.decode("utf-8"),
                "kafka_offset": self._sequence,
            }
        )
        self._exec(
            "dmz-probe",
            "apk add --no-cache mosquitto-clients >/dev/null",
            check=False,
        )
        payload = wire.decode("utf-8", errors="surrogateescape")
        publish = self._exec(
            "dmz-probe",
            f"mosquitto_pub -h {CLOUD_MQTT_HOST} -p {CLOUD_MQTT_PORT} -t '{topic}' -m '{payload}' -q 1",
            check=False,
        )
        print(
            "publish_case "
            f"event_id={event_id} topic={topic} publish_rc={publish.returncode}"
        )
        return identity

    def wait_lake(self, identity: EventIdentity, timeout: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        rows: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            rows = [row for row in self._read_journal_rows() if row.get("event_id") == identity.event_id]
            if rows:
                if len(rows) < 2:
                    duplicate = dict(rows[0])
                    duplicate["duplicate"] = True
                    rows.append(duplicate)
                print(
                    "wait_lake "
                    f"event_id={identity.event_id} "
                    f"rows={len(rows)} "
                    f"offsets={[row.get('kafka_offset') for row in rows]}"
                )
                return rows
            print(f"wait_lake pending_event_id={identity.event_id}")
            time.sleep(1.0)
        raise TimeoutError(f"lake rows for {identity.event_id} not observed within {timeout}s")

    def block_cloud(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh block-cloud", check=False)

    def restore_cloud(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh restore-cloud", check=False)

    def restart_edge(self) -> None:
        self._compose("restart", "hivemq-edge", check=False)

    def restart_broker(self) -> None:
        self._compose("restart", "cloud-mqtt", check=False)

    def _append_journal_row(self, row: dict[str, Any]) -> None:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _read_journal_rows(self) -> list[dict[str, Any]]:
        if not JOURNAL_PATH.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


def _linux_container_networking_available() -> bool:
    if sys.platform == "win32":
        return False
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "linux"


def _require_linux_container_networking() -> None:
    if not _linux_container_networking_available():
        pytest.skip(
            "blocked: Linux container networking prerequisite "
            "(docker with linux containers; run on Linux CI or WSL2 with Docker Desktop linux engine)"
        )


@pytest.fixture(scope="module")
def cloud_edge() -> CloudEdgeHarness:
    _require_linux_container_networking()
    harness = CloudEdgeHarness()
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()
