"""Resolve and load platform configuration from the root conf/ directory."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dynaconf import Dynaconf

_SETTINGS_ENV_VAR = "UNS_CONF_DIR"
_DOCKER_CONF_DIR = Path("/app/conf")
_REPO_CONF_MARKER = ("conf", "settings.yaml")


def _is_platform_settings(settings_file: Path) -> bool:
    """
    True for the repo-root conf that uses Dynaconf environments with a `default:` section.

    Leftover per-module conf/settings.yaml files (mqtt:/graphdb: at the top level) must
    not win when tests or services run from a module directory.
    """
    try:
        for line in settings_file.read_text(encoding="utf-8").splitlines():
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            return stripped.startswith("default:")
    except OSError:
        return False
    return False


def resolve_conf_dir() -> Path:
    """
    Return the directory containing settings.yaml and .secrets.yaml.

    Resolution order:
    1. UNS_CONF_DIR environment variable
    2. /app/conf when present in Docker
    3. Walk up from the current working directory looking for platform conf
    4. Repository root relative to this package (local development)
    5. /app/conf as the documented Docker mount even if the volume is empty
    """
    if env_dir := os.environ.get(_SETTINGS_ENV_VAR):
        return Path(env_dir).resolve()

    docker_settings = _DOCKER_CONF_DIR / _REPO_CONF_MARKER[1]
    if docker_settings.is_file():
        return _DOCKER_CONF_DIR

    for parent in (Path.cwd(), *Path.cwd().parents):
        candidate = parent.joinpath(*_REPO_CONF_MARKER)
        if candidate.is_file() and _is_platform_settings(candidate):
            return candidate.parent

    # 00_uns_config/src/uns_config/loader.py -> repo root (local editable install)
    package_conf = Path(__file__).resolve().parents[3] / "conf"
    if (package_conf / "settings.yaml").is_file():
        return package_conf

    # Docker copies uns_config to /00_uns_config, so parents[3] is filesystem root.
    # Keep the documented runtime location even if the volume is not mounted yet.
    return _DOCKER_CONF_DIR


@lru_cache
def get_settings(module_env: str = "default") -> Dynaconf:
    """Load merged settings for the given Dynaconf environment."""
    conf_dir = resolve_conf_dir()
    settings_kwargs: dict = {
        "envvar_prefix": "UNS",
        "environments": True,
        "env": module_env,
        "settings_files": ["settings.yaml", ".secrets.yaml"],
        "merge_enabled": True,
    }
    # Dynaconf walks root_path and raises OSError if it does not exist
    # (Docker image tests run without a conf volume).
    if conf_dir.is_dir():
        settings_kwargs["root_path"] = str(conf_dir)
    return Dynaconf(**settings_kwargs)
