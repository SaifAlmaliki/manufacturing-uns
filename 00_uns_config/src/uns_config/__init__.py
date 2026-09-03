"""Shared platform configuration for all UNS modules."""

from uns_config.loader import get_settings, resolve_conf_dir
from uns_config.platform import AuthConfig, PlatformConfig

__all__ = ["AuthConfig", "PlatformConfig", "get_settings", "resolve_conf_dir"]
