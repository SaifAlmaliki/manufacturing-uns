"""Canonical cloud-edge qualification fault matrix (Task 15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FaultStatus = Literal["contract", "integration", "blocked"]


@dataclass(frozen=True, slots=True)
class FaultCase:
    fault_id: str
    summary: str
    assertion: str
    status: FaultStatus
    blocker: str | None = None


FAULT_MATRIX: tuple[FaultCase, ...] = (
    FaultCase(
        "all_simulators_disabled",
        "All simulators disabled",
        "Base services and real-device configuration workflows remain functional; no dependency on fixture services or generated values.",
        "integration",
    ),
    FaultCase(
        "real_and_simulator_together",
        "Real-shaped endpoint and simulator configured together",
        "Both use identical released adapter code, with separate endpoint settings, identities, topics, and status.",
        "integration",
    ),
    FaultCase(
        "edge_sim_no_plc",
        "No PLC hardware, edge-sim enabled",
        "Current MQTT generators plus protocol test servers demonstrate VM-to-cloud data and cloud-to-edge configuration; no cloud-local data shortcut.",
        "contract",
    ),
    FaultCase(
        "mapping_changed_on_simulated_source",
        "Cloud mapping changed on a simulated source",
        "Applied revision/readback and new values/topics agree; old retained or queued data is not mistaken for new sampling.",
        "integration",
    ),
    FaultCase(
        "https_only_outage",
        "HTTPS-only outage during simulation",
        "Configuration stays pending while MQTT continues, then applies after HTTPS recovery.",
        "integration",
    ),
    FaultCase(
        "cloud_management_unavailable",
        "Cloud management unavailable",
        "Current Edge adapters keep running; pending configuration eventually reconciles.",
        "integration",
    ),
    FaultCase(
        "vm_power_loss_during_apply",
        "VM power loss during apply",
        "Journal survives; readback determines actual state; no false applied report.",
        "contract",
    ),
    FaultCase(
        "cloud_restart_after_snapshot",
        "Cloud/database restart after snapshot commit",
        "Pending desired state is still retrievable.",
        "blocked",
        blocker="Persistent cloud-management store not wired in qualification stubs",
    ),
    FaultCase(
        "https_response_loss_after_report",
        "HTTPS response loss after enrollment/report",
        "Same identity/report outcome; no duplicate enrollment or state regression.",
        "blocked",
        blocker="Requires fault injection on live agent HTTPS client",
    ),
    FaultCase(
        "duplicate_cloned_agent",
        "Duplicate/cloned agent",
        "Lease fences remote effects; installer prevents accidental identity cloning; cloned VM requires new enrollment.",
        "blocked",
        blocker="Lease fencing requires production agent + identity database",
    ),
    FaultCase(
        "bridge_wan_outage_edge_restart",
        "Bridge WAN outage plus Edge restart",
        "Licensed buffer survives; reconcile physical event IDs/coordinates and duplicates.",
        "integration",
    ),
    FaultCase(
        "broker_crash_after_puback",
        "Cloud MQTT crash immediately after PUBACK",
        "Measure pre-Kafka loss window and compare with accepted RPO.",
        "blocked",
        blocker="Qualified HiveMQ broker not available in isolated profile",
    ),
    FaultCase(
        "kafka_mapper_outage_full_queue",
        "Kafka/mapper downtime and full broker queue",
        "Bound pressure, expose drops/rejections, and report unsupported outage duration.",
        "blocked",
        blocker="Production mapper backpressure qualification not measured on stub broker",
    ),
    FaultCase(
        "store_historian_outage",
        "Store/historian outage",
        "Existing independent-consumer and upload-before-commit guarantees remain.",
        "contract",
    ),
    FaultCase(
        "partial_route_acl_release",
        "Partial route/ACL release",
        "New edge configuration is withheld; old route remains usable.",
        "blocked",
        blocker="Route release gating requires qualified broker ACL harness",
    ),
    FaultCase(
        "certificate_expiry_rotation",
        "Certificate expiry/revocation/rotation",
        "No TLS downgrade; active session revocation tested, not just reconnect refusal.",
        "blocked",
        blocker="Live mTLS revocation harness blocked until broker qualified",
    ),
    FaultCase(
        "outbox_publish_before_status_crash",
        "Outbox publish-before-status crash",
        "Same wrapper/source identity is retried; duplicate physical deliveries expected.",
        "contract",
    ),
    FaultCase(
        "http_flood_oversized_config",
        "HTTP flood or oversized configuration",
        "Explicit bounded refusal; no unbounded memory/disk growth.",
        "contract",
    ),
    FaultCase(
        "two_sites_identical_local_names",
        "Two sites with identical local names",
        "Scoped state/ACLs prevent collisions and cross-edge deletion.",
        "blocked",
        blocker="Multi-edge isolated harness not implemented",
    ),
    FaultCase(
        "unsupported_discovery_mapping",
        "Unsupported discovery or southbound mapping",
        "Clear unsupported/rejected state; no fallback cloud-to-OT call.",
        "contract",
    ),
)


def fault_ids() -> set[str]:
    return {case.fault_id for case in FAULT_MATRIX}
