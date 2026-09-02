"""Configuration for the OEE engine.

The only module that reads `conf/`. Everything downstream takes an `OeeConfig`, so a
test can construct one directly instead of writing a settings file. Mirrors
`uns_model.model_config.ModelConfig`: a frozen dataclass with a `from_settings`
classmethod, not module-level class attributes evaluated at import time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from uns_config import get_settings

LOGGER = logging.getLogger(__name__)

#: Dynaconf environment this module reads.
OEE_ENV = "oee"


@dataclass(frozen=True, slots=True)
class OeeConfig:
    """Everything the engine needs that is not master data."""

    mqtt_host: str | None
    mqtt_port: int = 1883
    mqtt_client_id: str = "uns_oee_client"
    mqtt_qos: int = 1
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_keep_alive: int = 60
    mqtt_version: int = 5
    mqtt_transport: str = "tcp"
    metrics_port: int = 9095
    scan_interval_seconds: float = 300.0
    settle_minutes: int = 15
    late_window_hours: int = 48
    backfill_days: int = 30
    metrics_table: str = "uns_metrics"

    @classmethod
    def from_settings(cls, module_env: str = OEE_ENV) -> OeeConfig:
        """Read the OEE settings from the platform `conf/` directory."""
        settings = get_settings(module_env)
        config = cls(
            mqtt_host=settings.get("mqtt.host"),
            mqtt_port=settings.get("mqtt.port", 1883),
            mqtt_client_id=settings.get("mqtt.client_id", "uns_oee_client"),
            # QoS 1 not 2: a duplicate KPI payload is harmless because the topic carries
            # the shift's final value, and a lost one is not.
            mqtt_qos=settings.get("mqtt.qos", 1),
            mqtt_username=settings.get("mqtt.username", None),
            mqtt_password=settings.get("mqtt.password", None),
            # The platform's shared `mqtt:` block already sets these three
            # (`conf/settings.yaml:53`-`:56`); read them rather than hardcode a second answer.
            mqtt_keep_alive=settings.get("mqtt.keep_alive", 60),
            mqtt_version=settings.get("mqtt.version", 5),
            mqtt_transport=settings.get("mqtt.transport", "tcp"),
            metrics_port=settings.get("oee.metrics_port", 9095),
            scan_interval_seconds=settings.get("oee.scan_interval_seconds", 300.0),
            settle_minutes=settings.get("oee.settle_minutes", 15),
            late_window_hours=settings.get("oee.late_window_hours", 48),
            backfill_days=settings.get("oee.backfill_days", 30),
            metrics_table=settings.get("historian.metrics_table", "uns_metrics"),
        )
        if not config.is_valid():
            LOGGER.error(
                "MQTT host not provided. Update key 'mqtt.host' in 'conf/settings.yaml' at the repository root"
            )
        return config

    def is_valid(self) -> bool:
        """Mandatory settings are present. Does not check that they are correct."""
        return bool(self.mqtt_host and self.mqtt_host.strip())
