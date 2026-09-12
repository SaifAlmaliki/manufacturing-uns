"""Pytest fixtures for the isolated cloud-edge qualification harness."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
COMPOSE_FILE = Path(__file__).with_name("compose.yml")
EDGE_SIM_CONNECTIONS = REPO_ROOT / "deploy" / "edge" / "simulation" / "connections.json"
EDGE_SIM_FIXTURES = REPO_ROOT / "conf" / "simulator" / "protocols" / "fixtures.json"
PROJECT_NAME = "uns-cloud-edge-qualification"
DMZ_MGMT_HOST = "172.30.21.10"
DMZ_MGMT_PORT = 8443
HIVEMQ_EDGE_HOST = "hivemq-edge"
HIVEMQ_EDGE_PORT = 1883
QUALIFICATION_BOOT_ID = "cloud-edge-qualification-boot"
HARNESS_SERVICE = "uns-edge-agent"


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
class SourceDataResult:
    protocol: str
    revision: int
    topics: list[str]
    local_mqtt_payloads: dict[str, bytes]
    lake_rows: list[dict[str, Any]]
    values_match_fixture: bool
    lake_payloads_match_local_mqtt: bool
    uses_updated_mapping: bool = False


@dataclass(slots=True)
class CloudEdgeHarness:
    compose_file: Path = COMPOSE_FILE
    project_name: str = PROJECT_NAME
    _sequence: int = 0
    _started: bool = False
    _last_publish: dict[str, Any] | None = None

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

    def _harness_json(self, *args: str, check: bool = True) -> dict[str, Any]:
        quoted = " ".join(args)
        result = self._exec(HARNESS_SERVICE, f"python /app/harness_client.py {quoted}", check=check)
        if result.returncode != 0 and check:
            raise RuntimeError(result.stderr or result.stdout)
        return json.loads(result.stdout)

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

    def _wait_for_health(self, timeout: float = 300.0) -> None:
        deadline = time.monotonic() + timeout
        services = (
            "test-router",
            "dmz-management",
            "uns-edge-agent",
            "cloud-management",
            "cloud-mqtt",
            "cloud-kafka",
            "cloud-minio",
            "qualification-kafka-mapper",
            "qualification-lake-sink",
            "edge-bridge",
            "hivemq-edge",
            "opcua-simulator",
            "modbus-simulator",
            "protocol-collector",
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

    def firewall_stats(self) -> str:
        result = self._exec("test-router", "/etc/firewall-rules.sh stats", check=False)
        return result.stdout or result.stderr

    def _chain_packets(self, chain: str) -> int:
        stats = self.firewall_stats()
        in_chain = False
        past_column_header = False
        total = 0
        for line in stats.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"Chain {chain}"):
                in_chain = True
                past_column_header = False
                continue
            if not in_chain:
                continue
            if stripped.startswith("Chain "):
                break
            if not stripped:
                continue
            if not past_column_header:
                if stripped.startswith("pkts"):
                    past_column_header = True
                continue
            parts = line.split()
            if parts and parts[0].isdigit():
                total += int(parts[0])
        return total

    def _conntrack_count(self) -> int:
        stats = self.firewall_stats()
        for line in stats.splitlines():
            if line.startswith("--- conntrack ---"):
                continue
            if line.strip().isdigit():
                return int(line.strip())
        match = re.search(r"(\d+)\s+flow entries", stats)
        return int(match.group(1)) if match else 0

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
        deny_before = self._chain_packets("UNS_CLOUD_TO_DMZ")
        self._exec("cloud-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        result = self._exec(
            "cloud-probe",
            f"nc -z -w2 {DMZ_MGMT_HOST} {DMZ_MGMT_PORT}",
            check=False,
        )
        deny_after = self._chain_packets("UNS_CLOUD_TO_DMZ")
        counters = self.firewall_counters()
        denied = [line for line in counters.splitlines() if "UNS_CLOUD_DMZ_MGMT_DENIED" in line]
        print(
            "cloud_management_probe="
            f"reachable={result.returncode == 0} "
            f"target={DMZ_MGMT_HOST}:{DMZ_MGMT_PORT} "
            f"deny_packets_before={deny_before} "
            f"deny_packets_after={deny_after} "
            f"deny_log_hits={len(denied)} "
            f"firewall_counters_tail={counters.splitlines()[-5:]}"
        )
        self._last_cloud_deny_delta = deny_after - deny_before
        return result.returncode == 0

    def assert_cloud_management_denied_by_firewall(self) -> None:
        assert getattr(self, "_last_cloud_deny_delta", 0) > 0, (
            "expected UNS_CLOUD_TO_DMZ iptables counter to increase"
        )

    def outbound_connectivity_report(self) -> dict[str, Any]:
        dmz_before = self._chain_packets("UNS_DMZ_TO_CLOUD")
        established_before = self._chain_packets("UNS_EDGE_ESTABLISHED")
        conntrack_before = self._conntrack_count()
        self._exec("dmz-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        management = self._exec(
            "dmz-probe",
            "nc -z -w2 cloud-management 443",
            check=False,
        ).returncode == 0
        mqtt = self._exec(
            "dmz-probe",
            "nc -z -w2 cloud-mqtt 1883",
            check=False,
        ).returncode == 0
        dmz_after = self._chain_packets("UNS_DMZ_TO_CLOUD")
        established_after = self._chain_packets("UNS_EDGE_ESTABLISHED")
        conntrack_after = self._conntrack_count()
        report = {
            "management": management,
            "mqtt": mqtt,
            "dmz_to_cloud_packets_delta": dmz_after - dmz_before,
            "established_packets_delta": established_after - established_before,
            "conntrack_delta": conntrack_after - conntrack_before,
            "firewall_counters": self.firewall_counters(),
        }
        print(f"outbound_connectivity={report}")
        return report

    def assert_outbound_established_replies(self, report: dict[str, Any]) -> None:
        assert report["dmz_to_cloud_packets_delta"] > 0, (
            "expected UNS_DMZ_TO_CLOUD iptables counter to increase"
        )
        assert report["established_packets_delta"] > 0, (
            "expected UNS_EDGE_ESTABLISHED iptables counter to increase for reply traffic"
        )

    def ot_can_reach_cloud_mqtt(self) -> bool:
        self._exec("ot-probe", "apk add --no-cache netcat-openbsd >/dev/null", check=False)
        result = self._exec(
            "ot-probe",
            "nc -z -w2 cloud-mqtt 1883",
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
        payload = self._harness_json("enroll", f"--edge-id={edge_id}")
        identity = EnrolledIdentity(
            edge_id=payload["edge_id"],
            management_subject=payload["management_subject"],
            bridge_subject=payload["bridge_subject"],
        )
        print(
            "enroll "
            f"edge_id={identity.edge_id} "
            f"management_subject={identity.management_subject} "
            f"bridge_subject={identity.bridge_subject} "
            f"tls_ca=CN=qualification-ca.uns"
        )
        return identity

    def save_connection(self, edge_id: str, protocol: str, settings: dict[str, Any]) -> int:
        settings_json = json.dumps(settings, separators=(",", ":"))
        payload = self._harness_json(
            "save-connection",
            f"--edge-id={edge_id}",
            f"--protocol={protocol}",
            f"--settings={shlex_quote(settings_json)}",
        )
        revision = int(payload["revision"])
        print(
            f"save_connection edge_id={edge_id} protocol={protocol} "
            f"revision={revision} phase={payload.get('phase')}"
        )
        return revision

    def wait_applied(self, edge_id: str, revision: int, timeout: float) -> VerifiedReport:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._exec(
                HARNESS_SERVICE,
                " ".join(
                    [
                        "python /app/harness_client.py wait-applied",
                        f"--edge-id={edge_id}",
                        f"--revision={revision}",
                        f"--timeout=5",
                    ]
                ),
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                payload = json.loads(result.stdout)
                if payload.get("phase") == "applied":
                    report = VerifiedReport(
                        edge_id=edge_id,
                        desired_revision=revision,
                        applied_revision=int(payload.get("applied_revision", revision)),
                        phase=payload["phase"],
                        certificate_subject=payload.get("certificate_subject"),
                    )
                    print(
                        "applied_report="
                        f"desired_revision={report.desired_revision} "
                        f"applied_revision={report.applied_revision} "
                        f"phase={report.phase} "
                        f"certificate_subject={report.certificate_subject}"
                    )
                    return report
            print(f"pending_revision edge_id={edge_id} revision={revision}")
            time.sleep(1.0)
        raise TimeoutError(f"revision {revision} for {edge_id} not applied within {timeout}s")

    def publish_case(self, application: str, site: str, body: bytes) -> EventIdentity:
        """Publish a DMZ business-app case via edge MQTT (not an OT simulator).

        Path: dmz-probe -> hivemq-edge -> edge-bridge -> cloud-mqtt -> kafka -> minio.
        OT simulators remain hivemq-edge-only per compose.yml.
        """
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
        self._last_publish = {"topic": topic, "wire": wire, "identity": identity}
        self._exec(
            "dmz-probe",
            "apk add --no-cache mosquitto-clients >/dev/null",
            check=False,
        )
        payload = wire.decode("utf-8", errors="surrogateescape")
        publish = self._exec(
            "dmz-probe",
            f"mosquitto_pub -h {HIVEMQ_EDGE_HOST} -p {HIVEMQ_EDGE_PORT} -t '{topic}' -m '{payload}' -q 1",
            check=False,
        )
        print(
            "publish_case "
            f"event_id={event_id} topic={topic} path=dmz->edge->cloud "
            f"publish_rc={publish.returncode}"
        )
        return identity

    def _replay_last_publish(self) -> None:
        if self._last_publish is None:
            raise RuntimeError("no publish to replay")
        topic = self._last_publish["topic"]
        wire = self._last_publish["wire"]
        payload = wire.decode("utf-8", errors="surrogateescape")
        self._exec(
            "dmz-probe",
            f"mosquitto_pub -h {HIVEMQ_EDGE_HOST} -p {HIVEMQ_EDGE_PORT} -t '{topic}' -m '{payload}' -q 1",
            check=False,
        )
        print(f"publish_replay topic={topic} path=dmz->edge->cloud")

    def wait_lake(self, identity: EventIdentity, timeout: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        replayed = False
        while time.monotonic() < deadline:
            rows = self._lake_rows(identity.event_id)
            if len(rows) >= 2:
                print(
                    "wait_lake "
                    f"event_id={identity.event_id} "
                    f"rows={len(rows)} "
                    f"offsets={[row.get('kafka_offset') for row in rows]}"
                )
                return rows
            if len(rows) == 1 and not replayed:
                self._replay_last_publish()
                replayed = True
            elif rows:
                print(
                    "wait_lake "
                    f"event_id={identity.event_id} "
                    f"rows={len(rows)} "
                    f"offsets={[row.get('kafka_offset') for row in rows]}"
                )
            else:
                print(f"wait_lake pending_event_id={identity.event_id}")
            time.sleep(2.0)
        raise TimeoutError(f"lake rows for {identity.event_id} not observed within {timeout}s")

    def _lake_rows(self, event_id: str) -> list[dict[str, Any]]:
        result = self._exec(
            "qualification-lake-sink",
            f"python /app/harness_client.py lake-rows --event-id={event_id}",
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return json.loads(result.stdout)

    def block_cloud(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh block-cloud", check=False)

    def restore_cloud(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh restore-cloud", check=False)

    def block_https(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh block-https", check=False)

    def restore_https(self) -> None:
        self._exec("test-router", "/etc/firewall-rules.sh restore-https", check=False)

    def stop_simulators(self) -> None:
        for service in (
            "opcua-simulator",
            "modbus-simulator",
            "oee-simulator",
            "multi-system-simulator",
            "protocol-collector",
        ):
            self._compose("stop", service, check=False)

    def restart_edge(self) -> None:
        self._compose("restart", "hivemq-edge", check=False)

    def restart_broker(self) -> None:
        self._compose("restart", "cloud-mqtt", check=False)

    def restart_cloud_management(self) -> None:
        self._compose("restart", "cloud-management", check=False)

    def _simulation_connections(self) -> dict[str, Any]:
        return json.loads(EDGE_SIM_CONNECTIONS.read_text(encoding="utf-8"))

    def _fixture_manifest(self) -> dict[str, Any]:
        data = json.loads(EDGE_SIM_FIXTURES.read_text(encoding="utf-8"))
        return data["profiles"]["edge_simulation"]

    def configure_simulated_source(self, protocol: str) -> int:
        connections = self._simulation_connections()
        key = "opcua" if protocol == "opcua" else "modbus"
        settings = dict(connections[key]["initial"])
        settings.pop("protocol", None)
        cloud_protocol = "opc_ua" if protocol == "opcua" else "modbus"
        return self.save_connection("edge-01", cloud_protocol, settings)

    def change_simulated_mapping(self, protocol: str) -> int:
        connections = self._simulation_connections()
        key = "opcua" if protocol == "opcua" else "modbus"
        settings = dict(connections[key]["remapped"])
        settings.pop("protocol", None)
        cloud_protocol = "opc_ua" if protocol == "opcua" else "modbus"
        return self.save_connection("edge-01", cloud_protocol, settings)

    def wait_source_data(
        self,
        protocol: str,
        revision: int,
        timeout: float,
        *,
        expect_remapped: bool = False,
    ) -> SourceDataResult:
        manifest = self._fixture_manifest()["manifest"]["revisions"]
        manifest_key = f"{protocol}_{'remapped' if expect_remapped else 'initial'}"
        expected = manifest[manifest_key]
        topics = list(expected["topics"])
        expected_values = expected["expected_values"]
        deadline = time.monotonic() + timeout
        local_payloads: dict[str, bytes] = {}
        while time.monotonic() < deadline:
            for topic in topics:
                if topic in local_payloads:
                    continue
                payload = self._capture_edge_mqtt(topic)
                if payload is not None:
                    local_payloads[topic] = payload
            if len(local_payloads) == len(topics):
                break
            time.sleep(2.0)
        if len(local_payloads) != len(topics):
            raise TimeoutError(f"protocol data for revision {revision} not observed on edge MQTT")

        lake_rows: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for topic in topics:
                rows = self._lake_rows_by_topic(topic)
                if rows:
                    lake_rows.extend(rows)
            if lake_rows:
                break
            time.sleep(2.0)
        if not lake_rows:
            raise TimeoutError(f"lake rows for protocol revision {revision} not observed")

        values_match = True
        for name, expected in expected_values.items():
            topic = next(
                (candidate for candidate in topics if name.lower() in candidate.lower()),
                None,
            )
            if topic is None:
                values_match = False
                break
            observed = json.loads(local_payloads[topic].decode("utf-8"))["value"]
            if abs(float(observed) - float(expected)) >= 0.01:
                values_match = False
                break
        lake_match = self._lake_matches_local_mqtt(local_payloads, lake_rows)
        return SourceDataResult(
            protocol=protocol,
            revision=revision,
            topics=topics,
            local_mqtt_payloads=local_payloads,
            lake_rows=lake_rows,
            values_match_fixture=values_match,
            lake_payloads_match_local_mqtt=lake_match,
            uses_updated_mapping=expect_remapped,
        )

    def _capture_edge_mqtt(self, topic: str) -> bytes | None:
        self._exec("dmz-probe", "apk add --no-cache mosquitto-clients >/dev/null", check=False)
        result = self._exec(
            "dmz-probe",
            (
                "timeout 3 mosquitto_sub -h hivemq-edge -p 1883 "
                f"-t '{topic}' -C 1 -W 2 || true"
            ),
            check=False,
        )
        line = (result.stdout or "").strip()
        return line.encode("utf-8") if line else None

    def _lake_rows_by_topic(self, topic: str) -> list[dict[str, Any]]:
        result = self._exec(
            "qualification-lake-sink",
            f"python /app/harness_client.py lake-topic-rows --topic={shlex_quote(topic)}",
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return json.loads(result.stdout)

    def _lake_matches_local_mqtt(
        self,
        local_payloads: dict[str, bytes],
        lake_rows: list[dict[str, Any]],
    ) -> bool:
        import base64

        for topic, payload in local_payloads.items():
            matching = [row for row in lake_rows if row.get("topic") == topic]
            if not matching:
                return False
            lake_payload = matching[0].get("payload", {})
            original_b64 = lake_payload.get("original_payload_base64")
            if not original_b64:
                return False
            if base64.b64decode(original_b64) != payload:
                return False
        return True


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
