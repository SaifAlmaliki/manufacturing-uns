"""Shared platform configuration for all UNS modules."""

from uns_config.loader import get_settings, resolve_conf_dir
from uns_config.platform import AuthConfig, PlatformConfig
from uns_config.uns_ingest import (
    MAPPER_ENVS,
    MAPPER_UNS_TOPICS,
    PLATFORM_OBSERVABILITY_PREFIX,
    UNS_WILDCARD,
    is_historic_event_topic,
)

__all__ = [
    "AuthConfig",
    "MAPPER_ENVS",
    "MAPPER_UNS_TOPICS",
    "PLATFORM_OBSERVABILITY_PREFIX",
    "PlatformConfig",
    "UNS_WILDCARD",
    "get_settings",
    "is_historic_event_topic",
    "resolve_conf_dir",
]
