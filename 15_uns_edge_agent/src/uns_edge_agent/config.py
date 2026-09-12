"""Agent runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

POLL_INTERVAL_SECONDS = 15.0
POLL_JITTER_SECONDS = 2.0
HEARTBEAT_INTERVAL_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 10.0
MAX_BACKOFF_SECONDS = 300.0
LEASE_RENEW_BEFORE_SECONDS = 30.0
MQTT_KEYSTORE_PASSWORD_LENGTH = 32


@dataclass(frozen=True, slots=True)
class AgentConfig:
    cloud_base_url: str
    data_dir: Path
    edge_api_url: str | None = None
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_jitter_seconds: float = POLL_JITTER_SECONDS
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS
    max_backoff_seconds: float = MAX_BACKOFF_SECONDS
    lease_renew_before_seconds: float = LEASE_RENEW_BEFORE_SECONDS

    @classmethod
    def from_env(cls) -> AgentConfig:
        data_dir = Path(os.environ.get("UNS_EDGE_DATA_DIR", "/var/lib/uns-edge-agent"))
        cloud_base_url = os.environ.get("UNS_EDGE_CLOUD_URL", "https://cloud-management:443")
        edge_api_url = os.environ.get("UNS_EDGE_API_URL")
        return cls(
            cloud_base_url=cloud_base_url.rstrip("/"),
            data_dir=data_dir,
            edge_api_url=edge_api_url,
        )

    @property
    def journal_path(self) -> Path:
        return self.data_dir / "journal.db"

    @property
    def credentials_dir(self) -> Path:
        return self.data_dir / "credentials"

    @property
    def enrollment_dir(self) -> Path:
        return self.data_dir / "enrollment"
