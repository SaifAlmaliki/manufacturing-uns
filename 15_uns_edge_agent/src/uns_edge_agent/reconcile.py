"""Crash-aware reconciliation of cloud desired state to local Edge adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from uns_config.edge_contracts import EdgeConfig, EdgeReport, validate_collection_only

from uns_edge_agent.edge_client import EdgeClient, EdgeClientError, snapshot_owned
from uns_edge_agent.journal import Journal
from uns_edge_agent.protocols._common import CompileError, CompiledAdapter
from uns_edge_agent.protocols.registry import compile_adapter

AGENT_VERSION = "0.9.38"


@dataclass(frozen=True, slots=True)
class AppliedState:
    revision: int
    digest: str


class ReconcileError(Exception):
    """Reconciliation failure with a stable reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


class Reconciler:
    """Apply EdgeConfig to the local Edge API with bounded recovery."""

    def __init__(
        self,
        edge_client: EdgeClient,
        *,
        boot_id: str,
        endpoint_allowlist: frozenset[str] = frozenset(),
        applied_state: AppliedState | None = None,
        resolve_secrets: Callable[[EdgeConfig], dict[str, bytes]] | None = None,
        agent_version: str = AGENT_VERSION,
    ) -> None:
        self._edge = edge_client
        self._boot_id = boot_id
        self._endpoint_allowlist = endpoint_allowlist
        self._applied_state = applied_state or AppliedState(revision=0, digest="")
        self._resolve_secrets = resolve_secrets or (lambda _config: {})
        self._agent_version = agent_version

    @property
    def applied_state(self) -> AppliedState:
        return self._applied_state

    def apply(
        self,
        config: EdgeConfig,
        *,
        journal: Journal | None = None,
        recovery_snapshot: dict[str, Any] | None = None,
    ) -> EdgeReport:
        validate_collection_only(config)
        if config.revision < self._applied_state.revision:
            return self._report(
                config,
                phase="ignored",
                applied_revision=self._applied_state.revision,
                applied_digest=self._applied_state.digest,
            )
        if (
            config.revision == self._applied_state.revision
            and config.digest == self._applied_state.digest
        ):
            current = self._edge.read_owned(config.edge_id)
            if self._matches_desired(config, current):
                return self._report(
                    config,
                    phase="applied",
                    applied_revision=self._applied_state.revision,
                    applied_digest=self._applied_state.digest,
                    adapter_results=self._adapter_results(current),
                )
        if (
            config.revision == self._applied_state.revision
            and config.digest != self._applied_state.digest
        ):
            raise ReconcileError("digest_mismatch")

        capabilities = self._edge.capabilities()
        resolved_secrets = self._resolve_secrets(config)
        compiled = self._compile_all(config, capabilities, resolved_secrets)
        read_for_snapshot = getattr(self._edge, "read_owned_for_snapshot", self._edge.read_owned)
        current = read_for_snapshot(config.edge_id)
        snapshot = recovery_snapshot if recovery_snapshot is not None else snapshot_owned(current)
        if journal is not None:
            journal.begin_apply(config, snapshot)

        touched: list[str] = []
        try:
            for item in compiled:
                self._edge.apply_adapter(item)
                touched.append(item.adapter_id)
            current = self._edge.read_owned(config.edge_id)
            if not self._matches_desired(config, current):
                raise EdgeClientError("readback_mismatch")
            for adapter_id in config.deleted_adapter_ids:
                self._edge.delete_owned(adapter_id)
            current = self._edge.read_owned(config.edge_id)
            self._applied_state = AppliedState(revision=config.revision, digest=config.digest)
            return self._report(
                config,
                phase="applied",
                applied_revision=config.revision,
                applied_digest=config.digest,
                adapter_results=self._adapter_results(current),
                capabilities=capabilities,
            )
        except (EdgeClientError, CompileError) as exc:
            reason = getattr(exc, "reason", str(exc))
            recovered = self._recover(snapshot, touched)
            current = self._edge.read_owned(config.edge_id)
            if recovered and self._snapshot_matches(current, snapshot):
                return self._report(
                    config,
                    phase="failed",
                    applied_revision=self._applied_state.revision,
                    applied_digest=self._applied_state.digest,
                    last_error_code=reason,
                    adapter_results=self._adapter_results(current),
                    capabilities=capabilities,
                )
            return self._report(
                config,
                phase="degraded",
                applied_revision=self._applied_state.revision,
                applied_digest=self._applied_state.digest,
                last_error_code=reason,
                adapter_results=self._adapter_results(current),
                capabilities=capabilities,
            )

    def resume_pending(self, journal: Journal) -> EdgeReport | None:
        pending = journal.pending_apply()
        if pending is None:
            return None
        from uns_config.edge_contracts import decode_edge_config

        restored = decode_edge_config(json.dumps(pending.config).encode("utf-8"))
        return self.apply(
            restored,
            journal=journal,
            recovery_snapshot=pending.recovery_snapshot,
        )

    def _compile_all(
        self,
        config: EdgeConfig,
        capabilities: dict[str, Any],
        resolved_secrets: dict[str, bytes],
    ) -> list[CompiledAdapter]:
        compiled: list[CompiledAdapter] = []
        for adapter in sorted(config.adapters, key=lambda item: item.adapter_id):
            compiled.append(
                compile_adapter(
                    adapter,
                    capabilities,
                    resolved_secrets,
                    endpoint_allowlist=self._endpoint_allowlist,
                )
            )
        return compiled

    def _recover(self, snapshot: dict[str, Any], touched: list[str]) -> bool:
        restore = getattr(self._edge, "restore_snapshot", None)
        if restore is not None:
            try:
                restore(snapshot)
                return True
            except Exception:
                return False
        try:
            for adapter_id in touched:
                if adapter_id in snapshot:
                    record = snapshot[adapter_id]
                    self._edge.apply_adapter(
                        CompiledAdapter(
                            adapter_id=adapter_id,
                            protocol_type=str(record["protocol_type"]),
                            adapter_body={
                                "id": adapter_id,
                                "type": str(record["protocol_type"]),
                                "config": dict(record["connection"]),
                            },
                            tags=[dict(tag) for tag in record.get("tags", [])],
                            mappings=[dict(mapping) for mapping in record.get("northbound_mappings", [])],
                        )
                    )
                else:
                    self._edge.delete_owned(adapter_id)
            return True
        except EdgeClientError:
            return False

    def _matches_desired(self, config: EdgeConfig, current: dict[str, Any]) -> bool:
        desired_ids = {adapter.adapter_id for adapter in config.adapters}
        for adapter in config.adapters:
            existing = current.get(adapter.adapter_id)
            if existing is None:
                return False
        for adapter_id, adapter in current.items():
            if adapter_id.startswith("catalog-") and adapter_id not in desired_ids:
                if adapter_id in config.deleted_adapter_ids:
                    continue
                return False
        return True

    def _snapshot_matches(self, current: dict[str, Any], snapshot: dict[str, Any]) -> bool:
        current_snapshot = snapshot_owned(current)
        return current_snapshot == snapshot

    def _adapter_results(self, current: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "adapter_id": adapter.adapter_id,
                "protocol_type": adapter.protocol_type,
                "status": "present",
            }
            for adapter in current.values()
        ]

    def _report(
        self,
        config: EdgeConfig,
        *,
        phase: str,
        applied_revision: int,
        applied_digest: str,
        adapter_results: list[dict[str, Any]] | None = None,
        last_error_code: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> EdgeReport:
        return EdgeReport(
            edge_id=config.edge_id,
            boot_id=self._boot_id,
            report_sequence=0,
            desired_revision=config.revision,
            applied_revision=applied_revision,
            applied_digest=applied_digest,
            phase=phase,
            adapter_results=tuple(adapter_results or ()),
            last_error_code=last_error_code,
            versions={"agent": self._agent_version},
            capabilities=capabilities or self._edge.capabilities(),
        )
